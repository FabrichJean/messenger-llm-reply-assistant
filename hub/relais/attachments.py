"""Pièces jointes : stockage, téléchargement à la demande, service des fichiers."""

import hashlib
import os
import re
import threading
from pathlib import Path
from urllib.parse import quote

from . import media
from .accounts import ACCOUNTS, mine
from .context import log
from .db import NOW, q, x
from .previews import link_cards
from .tls import SSL_CTX


media_waiters = {}   # (compte, nom de fichier) -> {"ev", "file", "size", "err"}


media_locks = {}     # (id, aperçu ?) -> verrou : un seul téléchargement à la fois par pièce jointe


media_fail = {}      # (id, aperçu ?) -> horodatage du dernier échec (on ne réessaie pas en boucle)


MEDIA_SEM = threading.Semaphore(4)


ATT_PLACEHOLDER = "[pièce jointe / sticker]"


ATT_LABEL = {"image": "[image]", "gif": "[GIF]", "sticker": "[sticker]", "video": "[vidéo]", "audio": "[message vocal]",
             "file": "[fichier]", "link": "[lien partagé]", "location": "[position]", "ephemeral": "[média éphémère]"}


ATT_KINDS = tuple(ATT_LABEL)


def att_id(account, thread, msg_id, idx):
    return hashlib.sha1(f"{account}|{thread}|{msg_id}|{idx}".encode()).hexdigest()[:24]


def media_dir(account):
    a = ACCOUNTS.get(account)
    if not a:
        return None
    d = Path(a.dir) / "media"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def store_attachment(acct, e):
    thread, mid = int(e.get("thread") or 0), str(e.get("id") or "")
    kind = e.get("kind") if e.get("kind") in ATT_KINDS else "file"
    if not thread or not mid:
        return
    key = f"{acct.name}:{thread}"
    aid = att_id(acct.name, thread, mid, int(e.get("idx") or 0))
    f = {
        "name": media.clean(e.get("name"), 120), "mime": media.clean(e.get("mime"), 80).lower(),
        "title": media.clean(e.get("title"), 200), "subtitle": media.clean(e.get("subtitle"), 200),
        "descr": media.clean(e.get("descr"), 400), "site": media.clean(e.get("site"), 80),
        "url": media.web_url(e.get("url"), 2000), "preview": media.web_url(e.get("preview"), 2000),
        "action": media.web_url(e.get("action"), 1000),
        "blob": str(e.get("blob") or "")[:6000] if re.fullmatch(r"[A-Za-z0-9+/=]*", str(e.get("blob") or "")) else "",
        "mtype": media.clean(e.get("mtype"), 20),
    }
    n = {k: max(0, min(int(e.get(k) or 0), 10**12)) for k in ("size", "w", "h", "dur")}
    src = "e2ee" if e.get("source") == "e2ee" else "classic"
    x("INSERT INTO attachments(id,account,chat_key,msg_id,idx,kind,name,mime,size,w,h,dur,url,preview,action,title,subtitle,descr,site,blob,mtype,source,ts) "
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
      + ",".join(f"{c}=CASE WHEN excluded.{c}<>'' THEN excluded.{c} ELSE attachments.{c} END" for c in
                 ("name", "mime", "url", "preview", "action", "title", "subtitle", "descr", "site", "blob", "mtype"))
      + ",kind=CASE WHEN excluded.kind<>'file' OR attachments.kind='' THEN excluded.kind ELSE attachments.kind END"
      + ",size=MAX(attachments.size,excluded.size),w=MAX(attachments.w,excluded.w),h=MAX(attachments.h,excluded.h),dur=MAX(attachments.dur,excluded.dur)",
      (aid, acct.name, key, mid, int(e.get("idx") or 0), kind, f["name"], f["mime"], n["size"], n["w"], n["h"], n["dur"], f["url"], f["preview"],
       f["action"], f["title"], f["subtitle"], f["descr"], f["site"], f["blob"], f["mtype"], src, int(e.get("ts") or NOW())))
    # le texte du message (pour la liste et pour le LLM) : une étiquette neutre, jamais le nom de fichier ni le titre (contenu non fiable)
    lab = ATT_LABEL[kind]
    x("UPDATE messages SET text=? WHERE id=? AND chat_key=? AND text=?", (lab, mid, key, ATT_PLACEHOLDER))
    x("UPDATE chats SET last_text=? WHERE key=? AND last_text=?", (lab, key, ATT_PLACEHOLDER))
    # images, GIF, stickers et aperçus de liens récents : récupérés tout de suite (les adresses de Meta expirent)
    if not e.get("history") and kind in ("image", "gif", "sticker", "link") and (f["url"] or f["preview"] or f["blob"]):
        threading.Thread(target=_prefetch, args=(aid,), daemon=True).start()


def _prefetch(aid):
    try:
        ensure_media(aid, preview=False)
    except Exception as ex:
        log("debug", f"Pièce jointe non préchargée : {ex}")


def drop_attachments(acct, key, mid):
    rows = q("SELECT id FROM attachments WHERE chat_key=? AND msg_id=?", (key, mid))
    d = media_dir(acct.name)
    for r in rows:
        for suffix in ("", "_p"):
            if d:
                try:
                    (d / (r["id"] + suffix)).unlink()
                except OSError:
                    pass
    if rows:
        x("DELETE FROM attachments WHERE chat_key=? AND msg_id=?", (key, mid))


def ensure_media(aid, preview=False):
    """Chemin du fichier local de la pièce jointe, après l'avoir récupérée si besoin. Lève une exception sinon."""
    rows = q("SELECT * FROM attachments WHERE id=?", (aid,))
    if not rows:
        raise FileNotFoundError("pièce jointe inconnue")
    a = rows[0]
    d = media_dir(a["account"])
    if d is None:
        raise FileNotFoundError("compte inconnu")
    name = aid + ("_p" if preview and a["source"] == "classic" and a["preview"] and a["url"] else "")
    path = d / name
    if path.exists() and path.stat().st_size > 0:
        return path
    fk = (aid, name.endswith("_p"))
    if NOW() - media_fail.get(fk, 0) < 60_000:
        raise RuntimeError("indisponible (dernier essai récent)")
    lock = media_locks.setdefault(fk, threading.Lock())
    with lock:
        if path.exists() and path.stat().st_size > 0:
            return path
        cap = media.MAX_BYTES.get(a["kind"], 15 * media.MB)
        try:
            with MEDIA_SEM:
                if a["source"] == "e2ee":
                    if not a["blob"]:
                        raise RuntimeError("pas de contenu à récupérer")
                    acct = ACCOUNTS.get(a["account"])
                    if not acct or not acct.state.get("e2ee"):
                        raise RuntimeError("canal chiffré non connecté")
                    if a["size"] and a["size"] > cap:
                        raise ValueError("fichier trop gros pour l'affichage")
                    w = {"ev": threading.Event(), "file": None, "err": None}
                    media_waiters[(a["account"], name)] = w
                    try:
                        if not acct.send({"op": "media", "req": name, "blob": a["blob"], "mtype": a["mtype"], "max": cap}):
                            raise RuntimeError("client indisponible")
                        if not w["ev"].wait(60):
                            raise RuntimeError("délai dépassé")
                        if w["err"]:
                            raise RuntimeError(str(w["err"])[:120])
                    finally:
                        media_waiters.pop((a["account"], name), None)
                    if not path.exists():
                        raise RuntimeError("fichier absent")
                    os.chmod(path, 0o600)
                else:
                    url = (a["preview"] if name.endswith("_p") else (a["url"] or a["preview"])) or a["url"]
                    if not url:
                        raise RuntimeError("pas d'adresse")
                    data, ctype = media.fetch(url, cap, ctx=SSL_CTX)
                    tmp = d / (name + ".part")
                    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    os.replace(tmp, path)
        except Exception as ex:
            media_fail[fk] = NOW()
            log("debug", f"Pièce jointe indisponible ({a['kind']}, {a['source']}) : {str(ex)[:120]}")
            raise
        media.evict(d)
        return path


def serve_media(handler, aid, preview, download):
    if not re.fullmatch(r"[0-9a-f]{24}", aid or ""):
        return handler._json({"error": "introuvable"}, 404)
    own = q("SELECT account FROM attachments WHERE id=?", (aid,))
    if not own or own[0]["account"] not in mine():
        return handler._json({"error": "introuvable"}, 404)
    try:
        path = ensure_media(aid, preview)
    except Exception:
        return handler._json({"error": "pièce jointe indisponible"}, 404)
    a = q("SELECT kind,name,mime FROM attachments WHERE id=?", (aid,))[0]
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(32)
    ctype, inline = media.serve_type(a["kind"], head, a["mime"])
    if download or not inline:
        inline = False
    rng = handler.headers.get("Range", "")
    start, end, code = 0, size - 1, 200
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
    if m and (m.group(1) or m.group(2)) and size:
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start = max(0, size - int(m.group(2)))
        if start > end or start >= size:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.end_headers()
            return
        code = 206
    handler.send_response(code)
    handler.send_header("Content-Type", ctype if inline else "application/octet-stream")
    handler.send_header("Content-Length", str(end - start + 1 if size else 0))
    handler.send_header("Accept-Ranges", "bytes")
    if code == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    fname = media.safe_name(a["name"], "fichier")
    handler.send_header("Content-Disposition", f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(fname)}")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
    handler.send_header("Cache-Control", "private, max-age=3600")
    handler.end_headers()
    if size:
        with open(path, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)


def attach_list(key, msgs):
    ids = [m["id"] for m in msgs]
    if not ids:
        return
    rows = q(f"SELECT id,msg_id,idx,kind,name,mime,size,w,h,dur,action,title,subtitle,descr,site,source,blob,url,preview "
             f"FROM attachments WHERE chat_key=? AND msg_id IN ({','.join('?' * len(ids))}) ORDER BY idx", (key, *ids))
    by = {}
    for r in rows:
        by.setdefault(r["msg_id"], []).append({
            "id": r["id"], "kind": r["kind"], "name": r["name"], "mime": r["mime"], "size": r["size"], "w": r["w"], "h": r["h"], "dur": r["dur"],
            "action": r["action"], "title": r["title"], "subtitle": r["subtitle"], "descr": r["descr"], "site": r["site"],
            "has_main": bool(r["url"] or r["preview"] or r["blob"]), "has_preview": bool(r["preview"] or (r["source"] == "e2ee" and r["blob"]))})
    for m in msgs:
        m["atts"] = by.get(m["id"], []) if not m.get("deleted") else []
    link_cards(key, msgs)
