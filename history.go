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
