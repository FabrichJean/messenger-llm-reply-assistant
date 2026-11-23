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
