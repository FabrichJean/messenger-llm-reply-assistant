package main

// Canal chiffré de bout en bout (E2EE) : notre client a son propre « appareil »
// (clés stockées dans un SQLite local). L'enregistrement de cet appareil modifie
// le compte Facebook : il n'est fait que si -register-e2ee est passé explicitement.

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"strconv"

	_ "github.com/mattn/go-sqlite3"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	waTypes "go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"

	"go.mau.fi/mautrix-meta/pkg/messagix"
)

// e2eeDevice : appareil chiffré de ce client (utile pour la restauration de l'historique).
var e2eeDevice *store.Device

// e2eeIncoming est appelé pour chaque message chiffré déchiffré.
type e2eeIncoming func(chat waTypes.JID, id string, sender waTypes.JID, fromMe bool, text string, tsMs int64)

// startE2EE ouvre le store de clés, (optionnellement) enregistre l'appareil, puis se connecte.
// Retourne (nil, nil) si aucun appareil n'est enregistré et que register est faux.
func startE2EE(ctx context.Context, client *messagix.Client, selfID int64, dbPath string, register bool,
	onMsg e2eeIncoming, onStatus func(state string, detail any),
	onEdit func(chat waTypes.JID, id, text string, tsMs int64), onDelete func(chat waTypes.JID, id string),
	onAtts func(chat waTypes.JID, id string, atts []attachment, tsMs int64)) (*whatsmeow.Client, error) {

	db, err := sql.Open("sqlite3", "file:"+dbPath+"?_foreign_keys=on&_busy_timeout=5000")
	if err != nil {
		return nil, fmt.Errorf("ouverture du store: %w", err)
	}
	container := sqlstore.NewWithDB(db, "sqlite3", nil)
	if err = container.Upgrade(ctx); err != nil {
		return nil, fmt.Errorf("migration du store: %w", err)
	}
	for _, f := range []string{dbPath, dbPath + "-wal", dbPath + "-shm"} {
		_ = os.Chmod(f, 0o600) // clés privées : lisible par nous seuls
	}
	dev, err := container.GetFirstDevice(ctx) // nouveau device non sauvegardé si le store est vide
	if err != nil {
		return nil, fmt.Errorf("lecture de l'appareil: %w", err)
	}
	isNew := dev.ID == nil
	if isNew && !register {
		onStatus("e2ee_not_registered", "aucun appareil chiffré : relancer avec -register-e2ee (modifie le compte)")
		return nil, nil
	}
	client.SetDevice(dev)
	e2eeDevice = dev
	if isNew {
		if err = client.RegisterE2EE(ctx, selfID); err != nil {
			return nil, fmt.Errorf("enregistrement de l'appareil: %w", err)
		}
		if err = dev.Save(ctx); err != nil {
			return nil, fmt.Errorf("sauvegarde de l'appareil: %w", err)
		}
		onStatus("e2ee_registered", nil)
	}

	cli, err := client.PrepareE2EEClient()
	if err != nil {
		return nil, fmt.Errorf("préparation du client chiffré: %w", err)
	}
	cli.AddEventHandler(func(raw any) {
		switch evt := raw.(type) {
		case *events.FBMessage:
			app := evt.GetConsumerApplication()
			if edit := app.GetPayload().GetContent().GetEditMessage(); edit != nil { // message modifié
				onEdit(evt.Info.Chat, edit.GetKey().GetID(), edit.GetMessage().GetText(), evt.Info.Timestamp.UnixMilli())
				return
			}
			if rev := app.GetPayload().GetApplicationData().GetRevoke(); rev != nil { // message supprimé
				onDelete(evt.Info.Chat, rev.GetKey().GetID())
				return
			}
			text := e2eeText(app)
			thread, _ := strconv.ParseInt(evt.Info.Chat.User, 10, 64)
			atts := e2eeAttachments(app, thread, evt.Info.Chat.String(), evt.Info.ID)
			if arm := evt.GetArmadillo(); arm != nil { // messages enrichis : posts / reels / liens partagés, galeries, éphémères
				if text == "" {
					text = armadilloText(arm)
				}
				atts = append(atts, armadilloAttachments(arm, thread, evt.Info.Chat.String(), evt.Info.ID)...)
				if len(atts) == 0 && text == "" {
					onStatus("e2ee_unhandled", fmt.Sprintf("%T", arm.GetPayload().GetContent().GetContent()))
				}
			}
			onMsg(evt.Info.Chat, evt.Info.ID, evt.Info.Sender, evt.Info.IsFromMe, text, evt.Info.Timestamp.UnixMilli())
			if len(atts) > 0 {
				onAtts(evt.Info.Chat, evt.Info.ID, atts, evt.Info.Timestamp.UnixMilli())
			}
		case *events.UndecryptableMessage:
			onStatus("e2ee_undecryptable", evt.Info.Chat.String())
		case *events.Connected:
			onStatus("e2ee_connected", nil)
		case *events.Disconnected:
			onStatus("e2ee_disconnected", nil)
		default:
			onStatus("e2ee_event", fmt.Sprintf("%T", raw))
		}
	})
	if err = cli.Connect(); err != nil {
		return nil, fmt.Errorf("connexion chiffrée: %w", err)
	}
	return cli, nil
}

// chatJID construit l'identifiant d'un chat chiffré 1:1 à partir de l'identifiant Facebook.
func chatJID(thread int64, chat string) (waTypes.JID, error) {
	if chat != "" {
		return waTypes.ParseJID(chat)
	}
	return waTypes.JID{User: strconv.FormatInt(thread, 10), Server: waTypes.MessengerServer}, nil
}

// sendE2EEText envoie un message texte chiffré.
func sendE2EEText(ctx context.Context, cli *whatsmeow.Client, to waTypes.JID, text string, otid int64) error {
	msg := &waConsumerApplication.ConsumerApplication{
		Payload: &waConsumerApplication.ConsumerApplication_Payload{
			Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{
				Content: &waConsumerApplication.ConsumerApplication_Content{
					Content: &waConsumerApplication.ConsumerApplication_Content_MessageText{
						MessageText: &waCommon.MessageText{Text: proto.String(text)},
					},
				},
			},
		},
	}
	_, err := cli.SendFBMessage(ctx, to, msg, nil, whatsmeow.SendRequestExtra{ID: waTypes.MessageID(strconv.FormatInt(otid, 10))})
	return err
}
