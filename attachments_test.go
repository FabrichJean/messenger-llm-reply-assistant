package main

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
	if got := e2eeText(app); got != "regarde" {
		t.Fatalf("légende: %q", got)
	}
	atts := e2eeAttachments(app, 42, "42@msgr", "mid1")
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
	a := e2eeAttachments(app, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "gif" || a[0]["mtype"] != "video" || a[0]["dur"] != int64(3000) {
		t.Fatalf("gif: %+v", a)
	}
	doc := &waMediaTransport.DocumentTransport{Integral: &waMediaTransport.DocumentTransport_Integral{Transport: transport("/v/d", "application/pdf", 5)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_DocumentMessage{
		DocumentMessage: &waConsumerApplication.ConsumerApplication_DocumentMessage{Document: sp(doc), FileName: proto.String("facture.pdf")}}})
	a = e2eeAttachments(app, 1, "1@msgr", "m")
	if len(a) != 1 || a[0]["kind"] != "file" || a[0]["name"] != "facture.pdf" || a[0]["mtype"] != "document" || a[0]["mime"] != "application/pdf" {
		t.Fatalf("doc: %+v", a)
	}
	st := &waMediaTransport.StickerTransport{Integral: &waMediaTransport.StickerTransport_Integral{Transport: transport("/v/s", "image/webp", 7)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_StickerMessage{
		StickerMessage: &waConsumerApplication.ConsumerApplication_StickerMessage{Sticker: sp(st)}}})
	if a = e2eeAttachments(app, 1, "1@msgr", "m"); len(a) != 1 || a[0]["kind"] != "sticker" {
		t.Fatalf("sticker: %+v", a)
	}
	au := &waMediaTransport.AudioTransport{Integral: &waMediaTransport.AudioTransport_Integral{Transport: transport("/v/a", "audio/ogg", 7)}}
	app = appWith(&waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_AudioMessage{
		AudioMessage: &waConsumerApplication.ConsumerApplication_AudioMessage{Audio: sp(au)}}})
	if a = e2eeAttachments(app, 1, "1@msgr", "m"); len(a) != 1 || a[0]["kind"] != "audio" {
		t.Fatalf("audio: %+v", a)
	}
}

func TestE2EELinkAndLocation(t *testing.T) {
