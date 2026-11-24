package main

// Historique des conversations chiffrées (E2EE) : restauration par code PIN (stockage sécurisé Messenger).
//
// - history_status : lecture seule (vérifie si le compte a une sauvegarde par PIN, ou si l'appareil d'historique est déjà inscrit).
// - history_enroll : demande le PIN (6 chiffres) ; ENREGISTRE un appareil d'historique sur le compte. Le PIN n'est
//                    jamais écrit sur disque ni journalisé.
// - history_fetch  : lit une page de messages plus anciens d'une conversation chiffrée.

import (
	"context"
	"encoding/json"
	"errors"
	"go.mau.fi/whatsmeow/proto/waArmadilloApplication"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"os"
	"strconv"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waArmadilloBackupMessage"
	"go.mau.fi/whatsmeow/proto/waMsgApplication"
	"go.mau.fi/whatsmeow/store"
	"google.golang.org/protobuf/proto"

	"go.mau.fi/mautrix-meta/pkg/messagix"
	"go.mau.fi/mautrix-meta/pkg/messagix/securehistory"
)

type historyStore struct {
	mu   sync.Mutex
	path string
	dev  *securehistory.Device
}

var hist = &historyStore{path: "history_device.json"}

func (h *historyStore) load() {
	h.mu.Lock()
	defer h.mu.Unlock()
	raw, err := os.ReadFile(h.path)
	if err != nil {
		return
	}
	var d securehistory.Device
	if json.Unmarshal(raw, &d) == nil {
		h.dev = &d
	}
}

func (h *historyStore) save(d *securehistory.Device) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	raw, err := json.Marshal(d)
	if err != nil {
		return err
	}
	tmp := h.path + ".tmp"
	if err = os.WriteFile(tmp, raw, 0o600); err != nil { // clés privées : lisible par nous seuls
		return err
	}
	if err = os.Rename(tmp, h.path); err != nil {
		return err
	}
	h.dev = d
	return nil
}

func (h *historyStore) clear() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.dev = nil
	_ = os.Remove(h.path)
}

func (h *historyStore) device() *securehistory.Device {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.dev
}

// historyStatus ne modifie rien : il lit seulement l'état.
func historyStatus(ctx context.Context, client *messagix.Client) map[string]any {
	if d := hist.device(); d != nil && d.ID != "" {
		return map[string]any{"type": "history", "state": "enrolled"}
	}
	_, err := client.GetSecureHistoryClient().GetBackup(ctx)
	switch {
	case errors.Is(err, securehistory.ErrNoPINBackup):
		return map[string]any{"type": "history", "state": "no_backup"}
	case err != nil:
		return map[string]any{"type": "history", "state": "unknown", "error": err.Error()}
	}
	return map[string]any{"type": "history", "state": "backup_available"}
}

// enrollHistory restaure l'accès à l'historique avec le PIN (ENREGISTRE un appareil d'historique sur le compte).
func enrollHistory(ctx context.Context, client *messagix.Client, wa *store.Device, selfID int64, pin string) map[string]any {
	fail := func(err error) map[string]any {
		out := map[string]any{"type": "history", "state": "error", "error": err.Error()}
		var rec *securehistory.RecoveryError
		if errors.As(err, &rec) && rec.AttemptsRemaining != nil {
			out["attempts_remaining"] = *rec.AttemptsRemaining
			out["error"] = "PIN refusé"
		}
		return out
	}
	if wa == nil {
		return fail(errors.New("canal chiffré non prêt"))
	}
	if d := hist.device(); d != nil && d.ID != "" {
		return map[string]any{"type": "history", "state": "enrolled"}
	}
	h := client.GetSecureHistoryClient()
	backup, err := h.GetBackup(ctx)
	if err != nil {
		return fail(err)
	}
	recovery, err := h.RecoverPIN(ctx, backup, []byte(pin))
	if err != nil {
		return fail(err)
	}
	virtual, err := h.GetVirtualDevice(ctx, backup, selfID, recovery.Code)
	if err != nil {
		return fail(err)
	}
	epochs, err := virtual.DeriveEpochs()
	if err != nil {
		return fail(err)
	}
	enrollment, err := virtual.PrepareDevice(backup.ID, h.RegistrationID, wa.IdentityKey, epochs)
	if err != nil {
		return fail(err)
	}
	if err = hist.save(enrollment.Device); err != nil { // d'abord sauvegarder (inscription non confirmée), comme le connecteur officiel
		return fail(err)
	}
	device, err := h.AddDevice(ctx, enrollment)
	if err != nil {
		var rejected *securehistory.EnrollmentError
		if errors.As(err, &rejected) {
			hist.clear()
		}
		return fail(err)
	}
	if err = hist.save(device); err != nil {
		return fail(err)
	}
	return map[string]any{"type": "history", "state": "enrolled"}
}

// fetchHistoryPage lit une page de messages chiffrés plus anciens que beforeMs et les émet.
func fetchHistoryPage(ctx context.Context, client *messagix.Client, chatUser string, beforeMs int64, count int,
	selfID int64, emit func(any)) map[string]any {
	dev := hist.device()
	out := map[string]any{"type": "history_fetched", "chat": chatUser}
	if dev == nil || dev.ID == "" {
		out["error"] = "appareil d'historique non inscrit"
		return out
	}
	if beforeMs <= 0 {
		beforeMs = time.Now().UnixMilli() + 60_000
	}
	page, err := client.GetSecureHistoryClient().FetchMessages(ctx, dev, chatUser, true, beforeMs, count)
	if err != nil {
		out["error"] = err.Error()
		return out
	}
	if page.Epochs != nil && len(page.Epochs.Edges) > 0 { // les clés d'époque évoluent : on les garde à jour
		if d2, e2 := dev.WithEpochs(page.Epochs); e2 == nil {
			_ = hist.save(d2)
			dev = d2
		}
	}
	n := 0
	for _, m := range page.Decrypt(ctx, dev, chatUser, selfID, false) {
		id, sender, text, ts, app, arm, ok := decodeArchive(m)
		if !ok {
			continue
		}
		thread, _ := strconv.ParseInt(chatUser, 10, 64)
		atts := e2eeAttachments(app, thread, chatUser+"@msgr", id)
		if arm != nil {
			if text == "" {
				text = armadilloText(arm)
			}
			atts = append(atts, armadilloAttachments(arm, thread, chatUser+"@msgr", id)...)
		}
		for _, a := range atts {
			a["ts"], a["history"] = ts, true
			emit(a)
		}
		emit(inMessage{Type: "message", ThreadID: thread, Chat: chatUser + "@msgr", MessageID: id, SenderID: sender,
			Text: text, TimeMs: ts, FromMe: sender == selfID, History: true, E2EE: true})
		n++
	}
	out["count"] = n
	if page.Range != nil {
		out["next"] = page.Range.Before
		out["has_more"] = page.Range.HasMoreBefore != nil && *page.Range.HasMoreBefore
	}
	return out
}

func decodeArchive(m *securehistory.DecryptedMessage) (id string, sender int64, text string, ts int64, capp *waConsumerApplication.ConsumerApplication, arm *waArmadilloApplication.Armadillo, ok bool) {
	if m == nil || m.Message == nil || m.Message.Message == nil {
		return
	}
	bm := m.Message.Message
	payload, isMsg := bm.GetPayload().(*waArmadilloBackupMessage.BackupMessage_EncryptedTransportMessage)
	if !isMsg {
		return
	}
	var app waMsgApplication.MessageApplication
	if proto.Unmarshal(payload.EncryptedTransportMessage, &app) != nil {
		return
	}
	decoded, err := whatsmeow.DecodeFBApplication(&app)
	if err != nil {
		return
	}
	meta := bm.GetMetadata()
	sender, _ = strconv.ParseInt(meta.GetSenderID(), 10, 64)
	capp = decoded.GetConsumerApplication()
	arm = decoded.GetArmadillo()
	text = e2eeText(capp)
	return meta.GetMessageID(), sender, text, m.Message.TimestampMS, capp, arm, meta.GetMessageID() != ""
}
