package attachments

import (
	"encoding/base64"
	"testing"

	"go.mau.fi/whatsmeow/proto/waArmadilloApplication"
	"go.mau.fi/whatsmeow/proto/waArmadilloXMA"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waMediaTransport"
	"google.golang.org/protobuf/proto"

	"go.mau.fi/mautrix-meta/pkg/messagix/table"
)

func transport(path, mime string, size uint64) *waMediaTransport.WAMediaTransport {
	return &waMediaTransport.WAMediaTransport{
		Integral:  &waMediaTransport.WAMediaTransport_Integral{DirectPath: proto.String(path), MediaKey: []byte("k"), FileSHA256: []byte("s"), FileEncSHA256: []byte("e")},
		Ancillary: &waMediaTransport.WAMediaTransport_Ancillary{Mimetype: proto.String(mime), FileLength: proto.Uint64(size)},
	}
}

func sp(m proto.Message) *waCommon.SubProtocol {
	b, _ := proto.Marshal(m)
	return &waCommon.SubProtocol{Payload: b, Version: proto.Int32(1)}
}

func appWith(c *waConsumerApplication.ConsumerApplication_Content) *waConsumerApplication.ConsumerApplication {
	return &waConsumerApplication.ConsumerApplication{Payload: &waConsumerApplication.ConsumerApplication_Payload{
		Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{Content: c}}}
}

func TestE2EEImage(t *testing.T) {
	img := &waMediaTransport.ImageTransport{
		Integral:  &waMediaTransport.ImageTransport_Integral{Transport: transport("/v/t1/x", "image/jpeg", 1234)},
		Ancillary: &waMediaTransport.ImageTransport_Ancillary{Width: proto.Uint32(640), Height: proto.Uint32(480)},
	}
	app := appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_ImageMessage{
		ImageMessage: &waConsumerApplication.ConsumerApplication_ImageMessage{Image: sp(img), Caption: &waCommon.MessageText{Text: proto.String("regarde")}}}})
	if got := E2EEText(app); got != "regarde" {
		t.Fatalf("légende: %q", got)
	}
	atts := E2EEAttachments(app, 42, "42@msgr", "mid1")
	if len(atts) != 1 || atts[0]["kind"] != "image" || atts[0]["mtype"] != "image" || atts[0]["w"] != int64(640) || atts[0]["size"] != int64(1234) {
		t.Fatalf("image: %+v", atts)
	}
	raw, _ := base64.StdEncoding.DecodeString(atts[0]["blob"].(string))
	var in waMediaTransport.WAMediaTransport_Integral
	if err := proto.Unmarshal(raw, &in); err != nil || in.GetDirectPath() != "/v/t1/x" {
		t.Fatalf("blob: %v %v", err, in.GetDirectPath())
	}
}

func TestE2EEGifDocStickerAudio(t *testing.T) {
	vid := &waMediaTransport.VideoTransport{
		Integral:  &waMediaTransport.VideoTransport_Integral{Transport: transport("/v/g", "video/mp4", 99)},
		Ancillary: &waMediaTransport.VideoTransport_Ancillary{GifPlayback: proto.Bool(true), Seconds: proto.Uint32(3)},
	}
	app := appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_VideoMessage{
		VideoMessage: &waConsumerApplication.ConsumerApplication_VideoMessage{Video: sp(vid)}}})
	a := E2EEAttachments(app, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "gif" || a[0]["mtype"] != "video" || a[0]["dur"] != int64(3000) {
		t.Fatalf("gif: %+v", a)
	}
	doc := &waMediaTransport.DocumentTransport{Integral: &waMediaTransport.DocumentTransport_Integral{Transport: transport("/v/d", "application/pdf", 5)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_DocumentMessage{
		DocumentMessage: &waConsumerApplication.ConsumerApplication_DocumentMessage{Document: sp(doc), FileName: proto.String("facture.pdf")}}})
	a = E2EEAttachments(app, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "file" || a[0]["name"] != "facture.pdf" || a[0]["mtype"] != "document" || a[0]["mime"] != "application/pdf" {
		t.Fatalf("doc: %+v", a)
	}
	st := &waMediaTransport.StickerTransport{Integral: &waMediaTransport.StickerTransport_Integral{Transport: transport("/v/s", "image/webp", 7)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_StickerMessage{
		StickerMessage: &waConsumerApplication.ConsumerApplication_StickerMessage{Sticker: sp(st)}}})
	if a = E2EEAttachments(app, 1, "1@msgr", "m"); len(a) != 1 || a[0]["kind"] != "sticker" {
		t.Fatalf("sticker: %+v", a)
	}
	au := &waMediaTransport.AudioTransport{Integral: &waMediaTransport.AudioTransport_Integral{Transport: transport("/v/a", "audio/ogg", 7)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_AudioMessage{
		AudioMessage: &waConsumerApplication.ConsumerApplication_AudioMessage{Audio: sp(au)}}})
	if a = E2EEAttachments(app, 1, "1@msgr", "m"); len(a) != 1 || a[0]["kind"] != "audio" {
		t.Fatalf("audio: %+v", a)
	}
}

func TestE2EELinkAndLocation(t *testing.T) {
	app := appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_ExtendedTextMessage{
		ExtendedTextMessage: &waConsumerApplication.ConsumerApplication_ExtendedTextMessage{
			Text: &waCommon.MessageText{Text: proto.String("lis ça https://exemple.fr/a")}, CanonicalURL: proto.String("https://exemple.fr/a"),
			Title: proto.String("Un titre"), Description: proto.String("Une description")}}})
	if got := E2EEText(app); got != "lis ça https://exemple.fr/a" {
		t.Fatalf("texte lien: %q", got)
	}
	a := E2EEAttachments(app, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "link" || a[0]["action"] != "https://exemple.fr/a" || a[0]["title"] != "Un titre" {
		t.Fatalf("lien: %+v", a)
	}
	loc := appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_LocationMessage{
		LocationMessage: &waConsumerApplication.ConsumerApplication_LocationMessage{Location: &waConsumerApplication.ConsumerApplication_Location{
			DegreesLatitude: proto.Float64(48.85), DegreesLongitude: proto.Float64(2.35), Name: proto.String("Paris")}}}})
	a = E2EEAttachments(loc, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "location" || a[0]["title"] != "Paris" {
		t.Fatalf("position: %+v", a)
	}
	if got := E2EEAttachments(appWith(&waConsumerApplication.ConsumerApplication_Content{}), 1, "x", "m"); len(got) != 0 {
		t.Fatalf("vide: %+v", got)
	}
}

func TestClassic(t *testing.T) {
	tb := &table.LSTable{
		LSInsertBlobAttachment: []*table.LSInsertBlobAttachment{
			{ThreadKey: 5, MessageId: "m1", AttachmentType: table.AttachmentTypeImage, PreviewUrl: "https://scontent.fbcdn.net/a.jpg", PreviewWidth: 800, PreviewHeight: 600},
			{ThreadKey: 5, MessageId: "m2", AttachmentType: table.AttachmentTypeAnimatedImage, PlayableUrl: "https://scontent.fbcdn.net/g.gif"},
			{ThreadKey: 5, MessageId: "m3", AttachmentType: table.AttachmentTypeFile, Filename: "a.zip", Filesize: 10, PlayableUrl: "https://cdn.fbsbx.com/a.zip"},
			{ThreadKey: 5, MessageId: "m4", AttachmentType: table.AttachmentTypeAudio, PlayableUrl: "https://cdn.fbsbx.com/v.mp4", PlayableDurationMs: 4000},
		},
		LSInsertStickerAttachment: []*table.LSInsertStickerAttachment{{ThreadKey: 5, MessageId: "m5", PlayableUrl: "https://scontent.fbcdn.net/s.webp"}},
		LSInsertXmaAttachment:     []*table.LSInsertXmaAttachment{{ThreadKey: 5, MessageId: "m6", AttachmentType: table.AttachmentTypeXMA, ActionUrl: "https://exemple.fr", TitleText: "T", ImageUrl: "https://external.fbcdn.net/i.jpg"}},
	}
	got := ClassicAttachments(tb)
	want := map[string]string{"m1": "image", "m2": "gif", "m3": "file", "m4": "audio", "m5": "sticker", "m6": "link"}
	if len(got) != len(want) {
		t.Fatalf("nombre: %d", len(got))
	}
	for _, a := range got {
		if want[a["id"].(string)] != a["kind"] {
			t.Errorf("%v : %v", a["id"], a["kind"])
		}
	}
	if got[0]["preview"] != "https://scontent.fbcdn.net/a.jpg" || got[0]["w"] != int64(800) {
		t.Errorf("image: %+v", got[0])
	}
	// message sans identifiant ou fil : ignoré
	if n := len(ClassicAttachments(&table.LSTable{LSInsertBlobAttachment: []*table.LSInsertBlobAttachment{{MessageId: "x"}}})); n != 0 {
		t.Errorf("sans fil: %d", n)
	}
}

func TestArmadilloSharedPost(t *testing.T) {
	prev := &waMediaTransport.ImageTransport{
		Integral:  &waMediaTransport.ImageTransport_Integral{Transport: transport("/v/p", "image/jpeg", 321)},
		Ancillary: &waMediaTransport.ImageTransport_Ancillary{Width: proto.Uint32(720), Height: proto.Uint32(900)},
	}
	arm := &waArmadilloApplication.Armadillo{Payload: &waArmadilloApplication.Armadillo_Payload{
		Payload: &waArmadilloApplication.Armadillo_Payload_Content{Content: &waArmadilloApplication.Armadillo_Content{
			Content: &waArmadilloApplication.Armadillo_Content_ExtendedContentMessage{ExtendedContentMessage: &waArmadilloXMA.ExtendedContentMessage{
				TitleText:   proto.String("Un post"),
				MessageText: proto.String("regarde ça"),
				Ctas: []*waArmadilloXMA.ExtendedContentMessage_CTA{
					{Title: proto.String("x"), NativeURL: proto.String("fb://post/1")},
					{Title: proto.String("Voir"), ActionURL: proto.String("https://www.facebook.com/share/p/abc/")},
				},
				Previews: []*waCommon.SubProtocol{sp(prev)},
			}}}}}}
	if ArmadilloText(arm) != "regarde ça" {
		t.Fatalf("texte: %q", ArmadilloText(arm))
	}
	a := ArmadilloAttachments(arm, 7, "7@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "link" || a[0]["title"] != "Un post" || a[0]["action"] != "https://www.facebook.com/share/p/abc/" ||
		a[0]["mtype"] != "xmapreview" || a[0]["blob"] == "" || a[0]["w"] != int64(720) {
		t.Fatalf("post partagé: %+v", a)
	}
	// galerie d'images
	gal := &waArmadilloApplication.Armadillo{Payload: &waArmadilloApplication.Armadillo_Payload{
		Payload: &waArmadilloApplication.Armadillo_Payload_Content{Content: &waArmadilloApplication.Armadillo_Content{
			Content: &waArmadilloApplication.Armadillo_Content_ImageGalleryMessage_{ImageGalleryMessage: &waArmadilloApplication.Armadillo_Content_ImageGalleryMessage{
				Images: []*waCommon.SubProtocol{sp(prev), sp(prev)}}}}}}}
	if g := ArmadilloAttachments(gal, 7, "7@msgr", "m"); len(g) != 2 || g[1]["idx"] != int64(1) || g[0]["kind"] != "image" {
		t.Fatalf("galerie: %+v", g)
	}
}
