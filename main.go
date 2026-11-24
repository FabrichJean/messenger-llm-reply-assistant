// messenger-lite : client Messenger ultra léger (sans navigateur).
//
//	Sortie  (stdout) : un JSON par ligne pour chaque message reçu.
//	Entrée  (stdin)  : un JSON par ligne {"thread": 123456789, "text": "salut"} pour envoyer.
//
// Cookies requis dans le fichier JSON : c_user, xs, datr (+ optionnels : sb, fr, wd...).
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand/v2"
	"os"
	"os/signal"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"go.mau.fi/whatsmeow"
	waTypes "go.mau.fi/whatsmeow/types"

	"go.mau.fi/mautrix-meta/pkg/messagix"
	"go.mau.fi/mautrix-meta/pkg/messagix/cookies"
	"go.mau.fi/mautrix-meta/pkg/messagix/socket"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
)

type inMessage struct {
	Type      string `json:"type"`
	ThreadID  int64  `json:"thread"`
	MessageID string `json:"id"`
	SenderID  int64  `json:"sender"`
	Text      string `json:"text"`
	TimeMs    int64  `json:"ts"`
	FromMe    bool   `json:"from_me"`
	History   bool   `json:"history,omitempty"` // true = message de l'historique chargé au démarrage
	E2EE      bool   `json:"e2ee,omitempty"`    // true = reçu par le canal chiffré
	Chat      string `json:"chat,omitempty"`    // JID du chat chiffré (pour répondre)
}

type outCommand struct {
	ThreadID int64  `json:"thread"`
	Chat     string `json:"chat,omitempty"` // JID d'un chat chiffré
	E2EE     bool   `json:"e2ee,omitempty"` // envoyer par le canal chiffré
	Text     string `json:"text"`
	Op       string `json:"op,omitempty"`     // "fetch" : charger des messages plus anciens d'un fil
	RefTs    int64  `json:"ref_ts,omitempty"` // fetch : horodatage du plus ancien message connu
	RefID    string `json:"ref_id,omitempty"` // fetch : identifiant du plus ancien message connu
	PIN      string `json:"pin,omitempty"`    // history_enroll : jamais journalisé ni stocké
	Before   int64  `json:"before,omitempty"` // history_fetch : messages plus anciens que cet horodatage (ms)
	Count    int    `json:"count,omitempty"`  // history_fetch : taille de page
	Req      string `json:"req,omitempty"`    // media : nom du fichier de sortie (hexadécimal)
	Blob     string `json:"blob,omitempty"`   // media : clés + chemin du média chiffré
	MType    string `json:"mtype,omitempty"`  // media : image | video | audio | document | linkthumb
	Max      int64  `json:"max,omitempty"`    // media : taille maximale acceptée (octets)
	On       bool   `json:"on,omitempty"`     // typing : afficher / retirer « est en train d'écrire »
	Kind     int64  `json:"kind,omitempty"`   // typing : type de fil Messenger (1 = conversation à deux)
}

func main() {
	cookiePath := flag.String("cookies", "cookies.json", "fichier JSON {nom: valeur} des cookies Messenger")
	verbose := flag.Bool("v", false, "logs détaillés sur stderr")
	useE2EE := flag.Bool("e2ee", true, "écouter le canal chiffré si un appareil est enregistré")
	registerE2EE := flag.Bool("register-e2ee", false, "ENREGISTRER un nouvel appareil chiffré sur le compte (modifie le compte)")
	e2eeDB := flag.String("e2ee-db", "e2ee.db", "fichier SQLite des clés de l'appareil chiffré")
	check := flag.Bool("check", false, "vérifier seulement que la session est valide puis quitter")
	flag.Parse()

	level := zerolog.ErrorLevel
	if *verbose {
		level = zerolog.DebugLevel
	}
	log := zerolog.New(zerolog.ConsoleWriter{Out: os.Stderr, TimeFormat: time.TimeOnly}).
		Level(level).With().Timestamp().Logger()

	raw, err := os.ReadFile(*cookiePath)
	if err != nil {
		fatal("lecture cookies: %v", err)
	}
	var kv map[string]string
	if err = json.Unmarshal(raw, &kv); err != nil {
		fatal("cookies.json invalide: %v", err)
	}
	c := &cookies.Cookies{Platform: types.Messenger}
	vals := make(map[cookies.MetaCookieName]string, len(kv))
	for k, v := range kv {
		vals[cookies.MetaCookieName(k)] = v
	}
	c.UpdateValues(vals)
	if missing := c.GetMissingCookieNames(); len(missing) > 0 {
		fatal("cookies manquants: %v", missing)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	client := messagix.NewClient(c, log, &messagix.Config{})
	selfID := c.GetUserID()
	var loadingHistory atomic.Bool
	startMs := time.Now().UnixMilli()

	var outMu sync.Mutex
	enc := json.NewEncoder(os.Stdout)
	emit := func(v any) {
		outMu.Lock()
		defer outMu.Unlock()
		_ = enc.Encode(v)
	}

	var seenMu sync.Mutex
	var lastDiag time.Time
	seen := make(map[string]struct{})
	handle := func(thread int64, id string, sender int64, text string, ts int64) {
		key := id + "\x00" + text
		seenMu.Lock()
		_, dup := seen[key]
		if dup {
			seenMu.Unlock()
			return
		}
		if len(seen) > 5000 {
			seen = make(map[string]struct{})
		}
		seen[key] = struct{}{}
		seenMu.Unlock()
		emit(inMessage{
			Type: "message", ThreadID: thread, MessageID: id, SenderID: sender, Text: text, TimeMs: ts,
			FromMe: sender == selfID, History: loadingHistory.Load() || ts < startMs,
		})
	}

	client.SetEventHandler(func(ctx context.Context, evt any) {
		switch e := evt.(type) {
		case *table.LSTable:
			if *verbose {
				emit(map[string]any{"type": "debug", "event": "LSTable", "fields": nonEmptyFields(e)})
			}
			for _, ct := range e.LSVerifyContactRowExists {
				if ct.Name != "" {
					emit(map[string]any{"type": "contact", "id": ct.ContactId, "name": ct.Name, "pic": ct.ProfilePictureUrl})
				}
			}
			for _, ct := range e.LSDeleteThenInsertContact {
				if ct.Name != "" {
					emit(map[string]any{"type": "contact", "id": ct.Id, "name": ct.Name, "pic": ct.ProfilePictureUrl})
				}
			}
			for _, th := range e.LSDeleteThenInsertThread {
				emit(map[string]any{"type": "thread", "id": th.ThreadKey, "name": th.ThreadName, "kind": int64(th.ThreadType), "ts": th.LastActivityTimestampMs, "pic": th.ThreadPictureUrl})
			}
			for _, th := range e.LSUpdateOrInsertThread {
				emit(map[string]any{"type": "thread", "id": th.ThreadKey, "name": th.ThreadName, "ts": th.LastActivityTimestampMs, "pic": th.ThreadPictureUrl})
			}
			for _, m := range e.LSUpsertMessage {
				if m.IsUnsent {
					emit(map[string]any{"type": "delete", "id": m.MessageId, "thread": m.ThreadKey})
					continue
				}
				handle(m.ThreadKey, m.MessageId, m.SenderId, m.Text, m.TimestampMs)
			}
			for _, m := range e.LSDeleteThenInsertMessage {
				if m.IsUnsent {
					emit(map[string]any{"type": "delete", "id": m.MessageId, "thread": m.ThreadKey})
					continue
				}
				handle(m.ThreadKey, m.MessageId, m.SenderId, m.Text, m.TimestampMs)
			}
			for _, m := range e.LSInsertMessage { // nouveaux messages en direct (champ ignoré par le connecteur officiel)
				if m.IsUnsent {
					emit(map[string]any{"type": "delete", "id": m.MessageId, "thread": m.ThreadKey})
					continue
				}
				handle(m.ThreadKey, m.MessageId, m.SenderId, m.Text, m.TimestampMs)
			}
			have := map[string]bool{}
			for _, a := range classicAttachments(e) {
				have[a["id"].(string)] = true
				a["history"] = loadingHistory.Load()
				emit(a)
			}
			// diagnostic : message sans texte et sans pièce jointe reconnue dans cette table -> on décrit la structure reçue
			// (noms de tables et indicateurs seulement, jamais de contenu) pour pouvoir ajouter le type manquant
			type mrow struct {
				id, text string
				unsent   bool
			}
			var rows []mrow
			for _, m := range e.LSUpsertMessage {
				rows = append(rows, mrow{m.MessageId, m.Text, m.IsUnsent})
			}
			for _, m := range e.LSDeleteThenInsertMessage {
				rows = append(rows, mrow{m.MessageId, m.Text, m.IsUnsent})
			}
			for _, m := range e.LSInsertMessage {
				rows = append(rows, mrow{m.MessageId, m.Text, m.IsUnsent})
			}
			for _, m := range rows {
				if m.text == "" && !m.unsent && !have[m.id] && time.Since(lastDiag) > time.Minute {
					lastDiag = time.Now()
					emit(map[string]any{"type": "diag", "fields": nonEmptyFields(e), "rows": attachmentShapes(e)})
					break
				}
			}
			for _, ed := range e.LSEditMessage {
				emit(map[string]any{"type": "edit", "id": ed.MessageID, "text": ed.Text, "count": ed.EditCount})
			}
			for _, d := range e.LSDeleteMessage {
				emit(map[string]any{"type": "delete", "id": d.MessageId, "thread": d.ThreadKey})
			}
		case *messagix.ConnectedEvent:
			emit(map[string]string{"type": "status", "state": "connected"})
		case *messagix.ReconnectedEvent:
			emit(map[string]string{"type": "status", "state": "reconnected"})
		case *messagix.TransientDisconnectEvent:
			emit(map[string]string{"type": "status", "state": "disconnected"})
		default:
			if *verbose {
				emit(map[string]string{"type": "debug", "event": fmt.Sprintf("%T", evt)})
			}
		case *messagix.PermanentErrorEvent:
			emit(map[string]any{"type": "status", "state": "fatal", "error": fmt.Sprint(e.Err)})
			stop()
		}
	})

	user, initial, err := client.LoadMessagesPage(ctx)
	if err != nil {
		fatal("chargement de la session (cookies expirés ? checkpoint ?): %v", err)
	}
	fmt.Fprintf(os.Stderr, "connecté en tant que %s (%d)\n", user.GetName(), selfID)
	if *check {
		fmt.Println("ok")
		os.Exit(0)
	}
	emit(map[string]any{"type": "self", "id": fmt.Sprint(selfID), "name": user.GetName()})
	// L'état initial contient l'historique récent : on le traite comme des messages normaux.
	loadingHistory.Store(true)
	client.HandleEvent(ctx, initial)
	loadingHistory.Store(false)

	if err = client.Connect(ctx); err != nil {
		fatal("connexion: %v", err)
	}
	defer client.Disconnect()

	hist.load()
	var e2eeCli *whatsmeow.Client
	if *useE2EE || *registerE2EE {
		e2eeCli, err = startE2EE(ctx, client, selfID, *e2eeDB, *registerE2EE,
			func(chat waTypes.JID, id string, sender waTypes.JID, fromMe bool, text string, tsMs int64) {
				key := id + "\x00" + text
				seenMu.Lock()
				_, dup := seen[key]
				seen[key] = struct{}{}
				seenMu.Unlock()
				if dup {
					return
				}
				thread, _ := strconv.ParseInt(chat.User, 10, 64)
				senderID, _ := strconv.ParseInt(sender.User, 10, 64)
				emit(inMessage{Type: "message", ThreadID: thread, Chat: chat.String(), MessageID: id, SenderID: senderID,
					Text: text, TimeMs: tsMs, FromMe: fromMe, History: tsMs < startMs, E2EE: true})
			},
			func(state string, detail any) {
				emit(map[string]any{"type": "status", "state": state, "detail": detail})
			},
			func(chat waTypes.JID, id, text string, tsMs int64) {
				emit(map[string]any{"type": "edit", "chat": chat.String(), "id": id, "text": text, "ts": tsMs})
			},
			func(chat waTypes.JID, id string) {
				emit(map[string]any{"type": "delete", "chat": chat.String(), "id": id})
			},
			func(chat waTypes.JID, id string, atts []attachment, tsMs int64) {
				for _, a := range atts {
					a["ts"] = tsMs
					a["history"] = tsMs < startMs
					emit(a)
				}
			})
		if err != nil {
			fmt.Fprintf(os.Stderr, "canal chiffré indisponible: %v\n", err)
		}
	}

	// Envoi : lecture des commandes sur stdin.
	go func() {
		sc := bufio.NewScanner(os.Stdin)
		sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
		for sc.Scan() {
			var cmd outCommand
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && strings.HasPrefix(cmd.Op, "history_") {
				go func(c outCommand) { // copie passée par valeur : on peut effacer cmd.PIN sans effet sur la goroutine
					switch c.Op {
					case "history_status":
						emit(historyStatus(ctx, client))
					case "history_enroll":
						if len(c.PIN) != 6 || strings.Trim(c.PIN, "0123456789") != "" {
							emit(map[string]any{"type": "history", "state": "error", "error": "le PIN doit faire 6 chiffres"})
							return
						}
						emit(enrollHistory(ctx, client, e2eeDevice, selfID, c.PIN))
					case "history_fetch":
						n := c.Count
						if n <= 0 || n > 100 {
							n = 30
						}
						emit(fetchHistoryPage(ctx, client, c.Chat, c.Before, n, selfID, emit))
					}
				}(cmd)
				cmd.PIN = ""
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && cmd.Op == "typing" {
				go func(c outCommand) { // indicateur « est en train d'écrire » (aucun message n'est envoyé)
					if c.E2EE || c.Chat != "" {
						if e2eeCli == nil {
							return
						}
						to, jerr := chatJID(c.ThreadID, c.Chat)
						if jerr != nil {
							return
						}
						state := waTypes.ChatPresencePaused
						if c.On {
							state = waTypes.ChatPresenceComposing
						}
						_ = e2eeCli.SendChatPresence(ctx, to, state, "")
						return
					}
					kind := c.Kind
					if kind == 0 {
						kind = 1
					}
					typing := int64(0)
					if c.On {
						typing = 1
					}
					_ = client.ExecuteStatelessTask(ctx, &socket.UpdatePresenceTask{
						ThreadKey: c.ThreadID, IsGroupThread: 0, IsTyping: typing, Attribution: 0, SyncGroup: 1, ThreadType: kind,
					})
				}(cmd)
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && cmd.Op == "media" {
				go func(c outCommand) { // déchiffrement d'une pièce jointe, à la demande du hub
					res := map[string]any{"type": "media_ready", "req": c.Req}
					path, size, err := downloadE2EEMedia(ctx, e2eeCli, c.Blob, c.MType, c.Req, c.Max)
					if err != nil {
						res["error"] = err.Error()
					} else {
						res["file"], res["size"] = path, size
					}
					emit(res)
				}(cmd)
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && cmd.Op == "contact" && cmd.ThreadID != 0 {
				// Cherche le profil (nom, photo) d'un identifiant précis.
				go func(id int64) {
					res := map[string]any{"type": "contact_done", "id": id, "found": false}
					if err := client.WaitUntilCanSendMessages(ctx, 30*time.Second); err == nil {
						tbl, ferr := client.ExecuteTasks(ctx, &socket.GetContactsFullTask{ContactID: id})
						if ferr != nil {
							res["error"] = ferr.Error()
						} else if tbl != nil && len(tbl.LSDeleteThenInsertContact) > 0 {
							res["found"] = true
							client.HandleEvent(ctx, tbl) // émet l'événement « contact » (nom + photo)
						}
					}
					emit(res)
				}(cmd.ThreadID)
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && cmd.Op == "threads" {
				go func() {
					// Charge les pages suivantes de la liste des conversations (le démarrage n'en donne qu'une partie).
					if err := client.WaitUntilCanSendMessages(ctx, 30*time.Second); err != nil {
						emit(map[string]string{"type": "error", "error": err.Error()})
						return
					}
					pages := 0
					for _, group := range []int64{1, 95} { // 1 = boîte principale, 95 = conversations chiffrées
						wctx, cancel := context.WithTimeout(ctx, 20*time.Second)
						_ = client.WaitForInitialThreadRange(wctx, group)
						cancel()
						for i := 0; i < 15; i++ {
							ks := client.GetSyncGroupKeyStore(group)
							if ks == nil || !ks.HasMoreBefore {
								break
							}
							prev := ks.MinThreadKey
							gen := client.ThreadRangeGeneration(group)
							_, tbl, ferr := client.FetchMoreThreads(ctx, group)
							if ferr != nil {
								emit(map[string]string{"type": "error", "error": ferr.Error()})
								break
							}
							if tbl == nil {
								break
							}
							client.HandleEvent(ctx, tbl)
							pages++
							wctx, cancel = context.WithTimeout(ctx, 15*time.Second)
							_ = client.WaitForThreadRange(wctx, group, gen)
							cancel()
							if *verbose {
								emit(map[string]any{"type": "debug", "event": "keystore", "group": group, "min_thread": ks.MinThreadKey, "has_more": ks.HasMoreBefore})
							}
							if ks.MinThreadKey == prev {
								break
							}
							time.Sleep(time.Second)
						}
					}
					emit(map[string]any{"type": "threads_done", "pages": pages})
				}()
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) == nil && cmd.Op == "fetch" && cmd.ThreadID != 0 {
				if err := client.WaitUntilCanSendMessages(ctx, 30*time.Second); err != nil {
					emit(map[string]string{"type": "error", "error": err.Error()})
					continue
				}
				ref := cmd.RefTs
				if ref == 0 {
					ref = time.Now().UnixMilli()
				}
				var task socket.Task = &socket.FetchMessagesTask{
					ThreadKey: cmd.ThreadID, Direction: 0, ReferenceTimestampMs: ref, ReferenceMessageId: cmd.RefID, SyncGroup: 1, Cursor: client.GetCursor(1),
				}
				if cmd.RefID == "" { // fil sans message connu : on l'ouvre (comme le connecteur officiel)
					task = &socket.CreateThreadTask{ThreadFBID: cmd.ThreadID, SyncGroup: 1}
				}
				tbl, ferr := client.ExecuteTasks(ctx, task)
				n := 0
				if ferr == nil && tbl != nil {
					n = len(tbl.LSUpsertMessage) + len(tbl.LSDeleteThenInsertMessage)
					client.HandleEvent(ctx, tbl)
				}
				if ferr != nil {
					emit(map[string]any{"type": "fetched", "thread": cmd.ThreadID, "count": 0, "error": ferr.Error()})
				} else {
					info := map[string]any{"type": "fetched", "thread": cmd.ThreadID, "count": n}
					if tbl != nil {
						info["fields"] = nonEmptyFields(tbl)
					}
					emit(info)
				}
				continue
			}
			if json.Unmarshal(sc.Bytes(), &cmd) != nil || (cmd.ThreadID == 0 && cmd.Chat == "") || cmd.Text == "" {
				emit(map[string]string{"type": "error", "error": "commande invalide"})
				continue
			}
			if cmd.E2EE || cmd.Chat != "" {
				if e2eeCli == nil {
					emit(map[string]string{"type": "error", "error": "canal chiffré non actif"})
					continue
				}
				to, jerr := chatJID(cmd.ThreadID, cmd.Chat)
				if jerr != nil {
					emit(map[string]string{"type": "error", "error": jerr.Error()})
					continue
				}
				otid := time.Now().UnixMilli()<<22 | rand.Int64N(1<<22)
				if serr := sendE2EEText(ctx, e2eeCli, to, cmd.Text, otid); serr != nil {
					emit(map[string]string{"type": "error", "error": serr.Error()})
				} else {
					emit(map[string]any{"type": "sent", "chat": to.String(), "e2ee": true})
				}
				continue
			}
			if err := client.WaitUntilCanSendMessages(ctx, 30*time.Second); err != nil {
				emit(map[string]string{"type": "error", "error": err.Error()})
				continue
			}
			otid := time.Now().UnixMilli()<<22 | rand.Int64N(1<<22)
			_, err := client.ExecuteTasks(ctx, &socket.SendMessageTask{
				ThreadId:         cmd.ThreadID,
				Otid:             otid,
				Source:           table.MESSENGER_INBOX_IN_THREAD,
				InitiatingSource: table.FACEBOOK_INBOX,
				SendType:         table.TEXT,
				SyncGroup:        1,
				Text:             cmd.Text,
			})
			if err != nil {
				emit(map[string]string{"type": "error", "error": err.Error()})
			} else {
				emit(map[string]any{"type": "sent", "thread": cmd.ThreadID})
			}
		}
	}()

	<-ctx.Done()
}

func fatal(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "erreur: "+f+"\n", a...)
	os.Exit(1)
}

// nonEmptyFields liste les champs non vides d'une table (debug : où passe le message ?).
func nonEmptyFields(v any) map[string]int {
	out := map[string]int{}
	rv := reflect.Indirect(reflect.ValueOf(v))
	for i := 0; i < rv.NumField(); i++ {
		f := rv.Field(i)
		if f.Kind() == reflect.Slice && f.Len() > 0 {
			out[rv.Type().Field(i).Name] = f.Len()
		}
	}
	return out
}
