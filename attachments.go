package main

// Pièces jointes : liens, images, GIF, stickers, vidéos, messages vocaux, fichiers, positions.
//
// Le client ne télécharge rien tout seul : il décrit chaque pièce jointe (évènement « attachment ») et le hub décide
// quand récupérer le contenu. Canal classique : une URL (CDN de Meta). Canal chiffré : un « blob » (clés + chemin du
// média, sérialisés) que l'opération « media » déchiffre à la demande.

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waArmadilloApplication"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waMediaTransport"
	"google.golang.org/protobuf/proto"

	"go.mau.fi/mautrix-meta/pkg/messagix/table"
)

type attachment = map[string]any

func attKind(t table.AttachmentType, mime string) string {
	switch t {
	case table.AttachmentTypeSticker, table.AttachmentTypeSelfieSticker, table.AttachmentTypeThirdPartySticker:
		return "sticker"
	case table.AttachmentTypeImage:
		if strings.EqualFold(mime, "image/gif") {
			return "gif"
		}
		return "image"
	case table.AttachmentTypeAnimatedImage:
		return "gif"
	case table.AttachmentTypeVideo:
		return "video"
	case table.AttachmentTypeAudio, table.AttachmentTypeSoundBite:
		return "audio"
	case table.AttachmentTypeFile:
		return "file"
	case table.AttachmentTypeXMA:
		return "link"
	case table.AttachmentTypeEphemeralImage, table.AttachmentTypeEphemeralVideo:
		return "ephemeral"
	}
	return "file"
}

func nz(m attachment, k string, v any) {
	switch x := v.(type) {
	case string:
		if x == "" {
			return
		}
	case int64:
		if x == 0 {
			return
		}
	case uint32:
		if x == 0 {
			return
		}
	}
	m[k] = v
}

// classicAttachments extrait les pièces jointes d'une table de synchronisation (canal classique).
func classicAttachments(e *table.LSTable) []attachment {
	var out []attachment
	add := func(thread int64, msgID string, idx int64, kind, name, mime string, size, w, h, dur int64, url, preview string) attachment {
		if thread == 0 || msgID == "" {
			return nil
		}
		a := attachment{"type": "attachment", "source": "classic", "thread": thread, "id": msgID, "idx": idx, "kind": kind}
		nz(a, "name", name)
		nz(a, "mime", mime)
		nz(a, "size", size)
		nz(a, "w", w)
		nz(a, "h", h)
		nz(a, "dur", dur)
		nz(a, "url", url)
		nz(a, "preview", preview)
		out = append(out, a)
		return a
	}
	for _, x := range e.LSInsertAttachment {
		mime := x.AttachmentMimeType
		if mime == "" {
			mime = x.PlayableUrlMimeType
		}
		a := add(x.ThreadKey, x.MessageId, x.AttachmentIndex, attKind(x.AttachmentType, mime), x.Filename, mime, x.Filesize,
			x.PreviewWidth, x.PreviewHeight, x.PlayableDurationMs, x.PlayableUrl, x.PreviewUrl)
		if a != nil && x.AttachmentType == table.AttachmentTypeXMA {
			nz(a, "title", x.TitleText)
		}
	}
	for _, x := range e.LSInsertBlobAttachment {
		mime := x.AttachmentMimeType
		if mime == "" {
			mime = x.PlayableUrlMimeType
		}
		a := add(x.ThreadKey, x.MessageId, x.AttachmentIndex, attKind(x.AttachmentType, mime), x.Filename, mime, x.Filesize,
			x.PreviewWidth, x.PreviewHeight, x.PlayableDurationMs, x.PlayableUrl, firstNonEmpty(x.PreviewUrlLarge, x.PreviewUrl))
		if a != nil && x.AttachmentType == table.AttachmentTypeXMA {
			nz(a, "title", x.TitleText)
			nz(a, "subtitle", x.SubtitleText)
			nz(a, "descr", x.DescriptionText)
		}
	}
	for _, x := range e.LSInsertStickerAttachment {
		add(x.ThreadKey, x.MessageId, 200+x.AttachmentIndex, "sticker", "", firstNonEmpty(x.PlayableUrlMimeType, x.ImageUrlMimeType), 0,
			x.PreviewWidth, x.PreviewHeight, 0, firstNonEmpty(x.PlayableUrl, x.ImageUrl), firstNonEmpty(x.PreviewUrl, x.ImageUrl))
	}
	for _, x := range e.LSInsertXmaAttachment {
		kind := attKind(x.AttachmentType, x.PlayableUrlMimeType)
		if kind == "file" && (x.ActionUrl != "" || x.TitleText != "") {
			kind = "link"
		}
		a := add(x.ThreadKey, x.MessageId, 100+x.AttachmentIndex, kind, x.Filename, x.PlayableUrlMimeType, x.Filesize, // 100+ : une carte de lien reste distincte d'une image du même message
			x.PreviewWidth, x.PreviewHeight, 0, x.PlayableUrl, firstNonEmpty(x.ImageUrl, x.PreviewUrl))
		if a != nil {
			nz(a, "action", x.ActionUrl)
			nz(a, "title", x.TitleText)
			nz(a, "subtitle", x.SubtitleText)
			nz(a, "descr", x.DescriptionText)
			nz(a, "site", x.SourceText)
		}
	}
	return out
}

func firstNonEmpty(v ...string) string {
	for _, s := range v {
		if s != "" {
			return s
		}
	}
	return ""
}

// ---------------------------------------------------------------- canal chiffré

type mediaRef struct {
	integral *waMediaTransport.WAMediaTransport_Integral
	mime     string
	size     int64
	w, h     int64
	dur      int64
}

func refFrom(tr *waMediaTransport.WAMediaTransport, w, h, dur uint32) *mediaRef {
	if tr == nil || tr.GetIntegral() == nil {
		return nil
	}
	return &mediaRef{integral: tr.GetIntegral(), mime: tr.GetAncillary().GetMimetype(), size: int64(tr.GetAncillary().GetFileLength()),
		w: int64(w), h: int64(h), dur: int64(dur)}
}

func (r *mediaRef) blob() string {
	b, err := proto.Marshal(r.integral)
	if err != nil {
		return ""
	}
	return base64.StdEncoding.EncodeToString(b)
}

// e2eeText : texte d'un message chiffré (texte simple, texte enrichi d'un lien, légende d'une image ou d'une vidéo).
func e2eeText(app *waConsumerApplication.ConsumerApplication) string {
	c := app.GetPayload().GetContent()
	if t := c.GetMessageText().GetText(); t != "" {
		return t
	}
	if t := c.GetExtendedTextMessage().GetText().GetText(); t != "" {
		return t
	}
	if t := c.GetImageMessage().GetCaption().GetText(); t != "" {
		return t
	}
	return c.GetVideoMessage().GetCaption().GetText()
}

// e2eeAttachments décrit les pièces jointes d'un message chiffré.
func e2eeAttachments(app *waConsumerApplication.ConsumerApplication, thread int64, chat, msgID string) []attachment {
	c := app.GetPayload().GetContent()
	var out []attachment
	mk := func(kind, mtype string, r *mediaRef, name string) attachment {
		a := attachment{"type": "attachment", "source": "e2ee", "thread": thread, "chat": chat, "id": msgID, "idx": int64(0), "kind": kind}
		if r != nil {
			a["blob"] = r.blob()
			a["mtype"] = mtype
			nz(a, "mime", r.mime)
			nz(a, "size", r.size)
			nz(a, "w", r.w)
			nz(a, "h", r.h)
			nz(a, "dur", r.dur)
		}
		nz(a, "name", name)
		return a
	}
	sub := func(sp interface{ GetPayload() []byte }, m proto.Message) bool {
		if sp == nil || len(sp.GetPayload()) == 0 {
			return false
		}
		return proto.Unmarshal(sp.GetPayload(), m) == nil
	}
	if im := c.GetImageMessage(); im != nil {
		var t waMediaTransport.ImageTransport
		if sub(im.GetImage(), &t) {
			r := refFrom(t.GetIntegral().GetTransport(), t.GetAncillary().GetWidth(), t.GetAncillary().GetHeight(), 0)
			kind := "image"
			if r != nil && strings.EqualFold(r.mime, "image/gif") {
				kind = "gif"
			}
			out = append(out, mk(kind, "image", r, ""))
		}
	}
	if vm := c.GetVideoMessage(); vm != nil {
		var t waMediaTransport.VideoTransport
		if sub(vm.GetVideo(), &t) {
			r := refFrom(t.GetIntegral().GetTransport(), t.GetAncillary().GetWidth(), t.GetAncillary().GetHeight(), t.GetAncillary().GetSeconds()*1000)
			kind := "video"
			if t.GetAncillary().GetGifPlayback() {
				kind = "gif"
			}
			out = append(out, mk(kind, "video", r, ""))
		}
	}
	if am := c.GetAudioMessage(); am != nil {
		var t waMediaTransport.AudioTransport
		if sub(am.GetAudio(), &t) {
			out = append(out, mk("audio", "audio", refFrom(t.GetIntegral().GetTransport(), 0, 0, t.GetAncillary().GetSeconds()*1000), ""))
		}
	}
	if dm := c.GetDocumentMessage(); dm != nil {
		var t waMediaTransport.DocumentTransport
		if sub(dm.GetDocument(), &t) {
			out = append(out, mk("file", "document", refFrom(t.GetIntegral().GetTransport(), 0, 0, 0), dm.GetFileName()))
		}
	}
	if sm := c.GetStickerMessage(); sm != nil {
		var t waMediaTransport.StickerTransport
		if sub(sm.GetSticker(), &t) {
			out = append(out, mk("sticker", "image", refFrom(t.GetIntegral().GetTransport(), t.GetAncillary().GetWidth(), t.GetAncillary().GetHeight(), 0), ""))
		}
	}
	if lm := c.GetLocationMessage(); lm != nil {
		a := mk("location", "", nil, "")
		loc := lm.GetLocation()
		nz(a, "title", firstNonEmpty(loc.GetName(), lm.GetAddress()))
		a["action"] = fmt.Sprintf("https://www.openstreetmap.org/?mlat=%.6f&mlon=%.6f#map=16/%.6f/%.6f",
			loc.GetDegreesLatitude(), loc.GetDegreesLongitude(), loc.GetDegreesLatitude(), loc.GetDegreesLongitude())
		out = append(out, a)
	}
	if xt := c.GetExtendedTextMessage(); xt != nil && (xt.GetCanonicalURL() != "" || xt.GetMatchedText() != "") {
		a := mk("link", "", nil, "")
		a["action"] = firstNonEmpty(xt.GetCanonicalURL(), xt.GetMatchedText())
		nz(a, "title", xt.GetTitle())
		nz(a, "descr", xt.GetDescription())
		var t waMediaTransport.ImageTransport
		if sub(xt.GetThumbnail(), &t) {
			if r := refFrom(t.GetIntegral().GetTransport(), t.GetAncillary().GetWidth(), t.GetAncillary().GetHeight(), 0); r != nil {
				a["blob"] = r.blob()
				a["mtype"] = "linkthumb"
				nz(a, "w", r.w)
				nz(a, "h", r.h)
			}
		}
		out = append(out, a)
	}
	if v := c.GetViewOnceMessage(); v != nil {
		out = append(out, mk("ephemeral", "", nil, ""))
	}
	return out
}

// previewRef décode une miniature d'un message enrichi (XMA) : image de transport, ou transport brut.
func previewRef(sp *waCommon.SubProtocol) *mediaRef {
	if sp == nil || len(sp.GetPayload()) == 0 {
		return nil
	}
	var it waMediaTransport.ImageTransport
	if proto.Unmarshal(sp.GetPayload(), &it) == nil {
		if r := refFrom(it.GetIntegral().GetTransport(), it.GetAncillary().GetWidth(), it.GetAncillary().GetHeight(), 0); r != nil {
			return r
		}
	}
	var wt waMediaTransport.WAMediaTransport
	if proto.Unmarshal(sp.GetPayload(), &wt) == nil {
		return refFrom(&wt, 0, 0, 0)
	}
	return nil
}

func httpURL(s string) string {
	if strings.HasPrefix(strings.ToLower(s), "http://") || strings.HasPrefix(strings.ToLower(s), "https://") {
		return s
	}
	return ""
}

// armadilloText : texte qui accompagne un message enrichi (post partagé, reel…).
func armadilloText(a *waArmadilloApplication.Armadillo) string {
	return a.GetPayload().GetContent().GetExtendedContentMessage().GetMessageText()
}

// armadilloAttachments décrit les messages « enrichis » du canal chiffré : posts, reels, histoires et liens partagés, galeries, éphémères.
func armadilloAttachments(a *waArmadilloApplication.Armadillo, thread int64, chat, msgID string) []attachment {
	c := a.GetPayload().GetContent()
	base := func(kind string) attachment {
		return attachment{"type": "attachment", "source": "e2ee", "thread": thread, "chat": chat, "id": msgID, "idx": int64(0), "kind": kind}
	}
	var out []attachment
	if x := c.GetExtendedContentMessage(); x != nil {
		at := base("link")
		nz(at, "title", firstNonEmpty(x.GetTitleText(), x.GetHeaderTitle()))
		nz(at, "subtitle", firstNonEmpty(x.GetSubtitleText(), x.GetHeaderSubtitle()))
		nz(at, "descr", x.GetOverlayDescription())
		nz(at, "site", x.GetOverlayTitle())
		for _, cta := range x.GetCtas() {
			if u := firstNonEmpty(httpURL(cta.GetActionURL()), httpURL(cta.GetNativeURL())); u != "" {
				at["action"] = u
				break
			}
		}
		prev := previewRef(x.GetHeaderImage())
		if prev == nil && len(x.GetPreviews()) > 0 {
			prev = previewRef(x.GetPreviews()[0])
		}
		if prev != nil {
			at["blob"] = prev.blob()
			at["mtype"] = "xmapreview"
			nz(at, "w", prev.w)
			nz(at, "h", prev.h)
		}
		out = append(out, at)
	}
	if g := c.GetImageGalleryMessage(); g != nil {
		for i, sp := range g.GetImages() {
			var t waMediaTransport.ImageTransport
			if sp != nil && proto.Unmarshal(sp.GetPayload(), &t) == nil {
				if r := refFrom(t.GetIntegral().GetTransport(), t.GetAncillary().GetWidth(), t.GetAncillary().GetHeight(), 0); r != nil {
					at := base("image")
					at["idx"] = int64(i)
					at["blob"], at["mtype"] = r.blob(), "image"
					nz(at, "mime", r.mime)
					nz(at, "size", r.size)
					nz(at, "w", r.w)
					nz(at, "h", r.h)
					out = append(out, at)
				}
			}
		}
	}
	if c.GetRavenMessage() != nil || c.GetRavenMessageMsgr() != nil {
		out = append(out, base("ephemeral"))
	}
	return out
}

var mediaTypes = map[string]whatsmeow.MediaType{
	"image": whatsmeow.MediaImage, "video": whatsmeow.MediaVideo, "audio": whatsmeow.MediaAudio,
	"document": whatsmeow.MediaDocument, "linkthumb": whatsmeow.MediaLinkThumbnail,
}

var reqName = regexp.MustCompile(`^[0-9a-f]{8,64}(_p)?$`)

// downloadE2EEMedia déchiffre un média chiffré et l'écrit dans media/<req> (dossier du compte, droits restreints).
func downloadE2EEMedia(ctx context.Context, cli *whatsmeow.Client, blob, mtype, req string, max int64) (string, int64, error) {
	if cli == nil {
		return "", 0, fmt.Errorf("canal chiffré non connecté")
	}
	tries := []string{mtype}
	if mtype == "xmapreview" { // type de clé inconnu pour les miniatures de messages enrichis : on essaie les deux
		tries = []string{"image", "linkthumb"}
	}
	for _, t := range tries {
		if _, ok := mediaTypes[t]; !ok {
			return "", 0, fmt.Errorf("demande invalide")
		}
	}
	if !reqName.MatchString(req) {
		return "", 0, fmt.Errorf("demande invalide")
	}
	raw, err := base64.StdEncoding.DecodeString(blob)
	if err != nil {
		return "", 0, fmt.Errorf("blob invalide")
	}
	var integral waMediaTransport.WAMediaTransport_Integral
	if err = proto.Unmarshal(raw, &integral); err != nil {
		return "", 0, fmt.Errorf("blob invalide")
	}
	var data []byte
	for _, t := range tries {
		if data, err = cli.DownloadFB(ctx, &integral, mediaTypes[t]); err == nil {
			break
		}
	}
	if err != nil {
		return "", 0, err
	}
	if max > 0 && int64(len(data)) > max {
		return "", 0, fmt.Errorf("fichier trop gros")
	}
	if err = os.MkdirAll("media", 0o700); err != nil {
		return "", 0, err
	}
	path := filepath.Join("media", req)
	if err = os.WriteFile(path, data, 0o600); err != nil {
		return "", 0, err
	}
	return path, int64(len(data)), nil
}

// attachmentShapes résume les lignes de pièces jointes d'une table : types et indicateurs seulement (aucun contenu).
func attachmentShapes(e *table.LSTable) []map[string]any {
	var out []map[string]any
	flag := func(table string, t table.AttachmentType, thread int64, msg string, vals map[string]string) {
		m := map[string]any{"table": table, "type": int64(t), "thread0": thread == 0, "msg0": msg == ""}
		for k, v := range vals {
			m[k] = v != ""
		}
		out = append(out, m)
	}
	for _, x := range e.LSInsertAttachment {
		flag("Attachment", x.AttachmentType, x.ThreadKey, x.MessageId, map[string]string{"playable": x.PlayableUrl, "preview": x.PreviewUrl, "title": x.TitleText})
	}
	for _, x := range e.LSInsertBlobAttachment {
		flag("Blob", x.AttachmentType, x.ThreadKey, x.MessageId, map[string]string{"playable": x.PlayableUrl, "preview": x.PreviewUrl, "title": x.TitleText})
	}
	for _, x := range e.LSInsertXmaAttachment {
		flag("Xma", x.AttachmentType, x.ThreadKey, x.MessageId, map[string]string{"playable": x.PlayableUrl, "preview": x.PreviewUrl, "image": x.ImageUrl, "action": x.ActionUrl, "title": x.TitleText})
	}
	for _, x := range e.LSInsertStickerAttachment {
		flag("Sticker", 0, x.ThreadKey, x.MessageId, map[string]string{"playable": x.PlayableUrl, "preview": x.PreviewUrl})
	}
	return out
}
