"""Aperçus de liens (anti-SSRF) et images associées."""

import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlparse

from . import media
from .accounts import ACCOUNTS
from .config import DATA
from .context import acct_of, log
from .db import NOW, q, setting, x
from .tls import SSL_CTX


LP_SEM = threading.Semaphore(2)


LP_BUSY = set()


LP_CAP = 200 * media.MB


def _lp_key():
    f = DATA / ".lpkey"
    try:
        return f.read_bytes()
    except OSError:
        k = os.urandom(32)
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(k)
        return k


LP_KEY = _lp_key()


def lp_hash(url):
    """Identifiant d'aperçu = HMAC secret de l'adresse : impossible à deviner même en connaissant le lien (capacité non devinable)."""
    return hmac.new(LP_KEY, url.encode(), hashlib.sha256).hexdigest()[:24]


def lp_dir():
    d = DATA / "linkcache"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


FB_HOSTS = ("facebook.com", "fb.com", "fb.watch", "messenger.com")


def is_fb(url):
    h = (urlparse(url).hostname or "").lower()
    return any(h == d or h.endswith("." + d) for d in FB_HOSTS)


def fb_cookie(account):
    """Cookie de session du compte (pour que Facebook montre le contenu d'un lien comme à ton navigateur). Jamais journalisé ni renvoyé à l'interface."""
    a = ACCOUNTS.get(account)
    if not a:
        return ""
    try:
        ck = json.loads((Path(a.dir) / "cookies.json").read_text())
    except (OSError, ValueError):
        return ""
    return "; ".join(f"{k}={ck[k]}" for k in ("c_user", "xs", "datr", "sb", "fr") if ck.get(k) and re.fullmatch(r"[A-Za-z0-9%._:/+=-]+", str(ck[k])))


def lp_request(url, account=None):
    """Lance (une seule fois) la récupération de l'aperçu d'un lien. Rien n'est téléchargé tant que la conversation n'est pas ouverte."""
    h = lp_hash(url)
    row = q("SELECT status,ts,auth FROM link_previews WHERE h=?", (h,))
    use_fb = bool(account and is_fb(url) and setting("link_preview_fb", account) == "1" and fb_cookie(account))
    if h in LP_BUSY:
        return
    if row and (row[0]["status"] == "ok" or (NOW() - row[0]["ts"] < 6 * 3600_000 and not (use_fb and not row[0]["auth"]))):
        return
    LP_BUSY.add(h)
    threading.Thread(target=_lp_fetch, args=(url, h, account if use_fb else None), daemon=True).start()


def _lp_fetch(url, h, account=None):
    info, has_img, status = {"title": "", "descr": "", "site": "", "image": ""}, 0, "none"
    try:
        with LP_SEM:
            ck = fb_cookie(account) if account else ""
            raw, ctype, final, hdr = media.fetch_public(url, 512 * 1024, timeout=10, ctx=SSL_CTX, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                                                        cookie=ck, cookie_hosts=FB_HOSTS)
            if ctype in ("text/html", "application/xhtml+xml", ""):
                info = media.parse_preview(raw, hdr, final)
                if info.get("wall"):
                    info = {"title": "", "descr": "", "site": "", "image": ""}
                if info["image"]:
                    try:
                        data, _ct, _f, _h = media.fetch_public(info["image"], 3 * media.MB, timeout=10, ctx=SSL_CTX, accept="image/*")   # image : jamais de cookie
                        if media.sniff(data, "") in ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"):
                            fd = os.open(lp_dir() / h, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                            with os.fdopen(fd, "wb") as fh:
                                fh.write(data)
                            has_img = 1
                    except Exception:
                        pass
                if info["title"] or info["descr"] or has_img:
                    status = "ok"
            media.evict(lp_dir(), LP_CAP)
    except Exception as ex:
        log("debug", f"Aperçu de lien indisponible : {str(ex)[:80]}")
    finally:
        x("INSERT OR REPLACE INTO link_previews(h,url,status,title,descr,site,image,ts,auth) VALUES(?,?,?,?,?,?,?,?,?)",
          (h, url, status, info["title"], info["descr"], info["site"], has_img, NOW(), 1 if account else 0))
        LP_BUSY.discard(h)


def link_cards(key, msgs):
    """Cartes d'aperçu pour les liens écrits dans les messages (quand Messenger n'en a pas fourni)."""
    acct = acct_of(key)
    if setting("link_preview", acct) != "1":
        return
    enrich_links(key, msgs)
    fresh = 0
    for m in msgs[-60:]:
        if m.get("deleted") or not m.get("text"):
            continue
        if any(a["kind"] == "link" for a in m.get("atts") or []):
            continue
        for u in media.urls_in(m["text"]):
            h = lp_hash(u)
            row = q("SELECT status,title,descr,site,image FROM link_previews WHERE h=?", (h,))
            if (not row or (row[0]["status"] != "ok" and is_fb(u))) and fresh < 6:
                lp_request(u, acct)
                fresh += 1
            r = row[0] if row else None
            host = (urlparse(u).hostname or "").removeprefix("www.")
            m.setdefault("atts", []).append({
                "id": "lp" + h, "kind": "link", "name": "", "mime": "", "size": 0, "w": 0, "h": 0, "dur": 0, "action": u,
                "title": (r["title"] if r else "") or "", "subtitle": "", "descr": (r["descr"] if r else "") or "",
                "site": ((r["site"] if r else "") or host), "has_main": False, "has_preview": False,
                "img": ("/linkimg/" + h) if r and r["image"] else "", "pending": not row})


def enrich_links(key, msgs):
    """Messenger fournit parfois une carte de lien vide (adresse seule) : on la complète avec l'aperçu de la page."""
    fresh = 0
    for m in msgs[-60:]:
        for a in m.get("atts") or []:
            if a["kind"] != "link" or a["id"].startswith("lp") or a["title"] or a["has_preview"] or not a["action"] or not media.web_url(a["action"]):
                continue
            h = lp_hash(a["action"])
            row = q("SELECT status,title,descr,site,image FROM link_previews WHERE h=?", (h,))
            if (not row or (row[0]["status"] != "ok" and is_fb(a["action"]))) and fresh < 6:
                lp_request(a["action"], acct_of(key))
                fresh += 1
            if row and row[0]["status"] == "ok":
                r = row[0]
                a.update(title=r["title"] or "", descr=a["descr"] or r["descr"] or "", site=a["site"] or r["site"] or "", img=("/linkimg/" + h) if r["image"] else "")
            elif not row:
                a["pending"] = True


def serve_linkimg(handler, h):
    if not re.fullmatch(r"[0-9a-f]{24}", h or ""):
        return handler._json({"error": "introuvable"}, 404)
    f = lp_dir() / h
    try:
        data = f.read_bytes()
    except OSError:
        return handler._json({"error": "introuvable"}, 404)
    ctype = media.sniff(data[:32], "")
    if ctype not in ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"):
        return handler._json({"error": "introuvable"}, 404)
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
    handler.send_header("Cache-Control", "private, max-age=86400")
    handler.end_headers()
    handler.wfile.write(data)
