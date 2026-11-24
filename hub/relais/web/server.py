"""Serveur HTTP : en-têtes de sécurité, CSP, pages, routes GET, connexion."""

import base64
import hashlib
import json
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlparse

from .. import auth as authmod
from .. import media
from ..accounts import own_chat
from ..attachments import serve_media
from ..config import ALLOWED_HOSTS, DATA, HERE, SECURE_COOKIE, TRUST_PROXY
from ..context import AUTH, REQ, clean, cur_name, log
from ..db import q
from ..login import LOGIN, _lkey, ext_import, ext_zip
from ..previews import serve_linkimg
from ..tls import SSL_CTX
from .pages import page
from .readers import api_chat, api_state, api_stats
from .routes import post


AVATAR_HOSTS = (".fbcdn.net", ".facebook.com", ".fbsbx.com")


def avatar_bytes(key):
    """Photo de profil en cache local (téléchargée côté serveur, jamais par le navigateur)."""
    r = q("SELECT pic FROM chats WHERE key=? AND pic<>''", (key,))
    if not r:
        return None
    url = r[0]["pic"]
    host = (urlparse(url).hostname or "")
    if urlparse(url).scheme != "https" or not host.endswith(AVATAR_HOSTS):
        return None  # liste blanche : pas de requête vers un hôte arbitraire
    f = DATA / "avatars" / (hashlib.sha1(url.encode()).hexdigest() + ".img")
    if f.exists():
        return f.read_bytes()
    try:
        data, ctype = media.fetch(url, 2_000_000, timeout=10, ctx=SSL_CTX)   # hôtes autorisés, redirections revalidées, taille limitée
        if not ctype.startswith("image/") or media.sniff(data[:32], "") not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            return None
        f.write_bytes(data)
        return data
    except Exception:
        return None


SEC_DEFAULTS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin", "Cache-Control": "no-store",
}


def csp_for(html_bytes):
    """Politique de contenu stricte : seuls les scripts en ligne dont l'empreinte est connue s'exécutent (une injection HTML ne peut donc pas lancer de script)."""
    hashes = [base64.b64encode(hashlib.sha256(m).digest()).decode() for m in re.findall(rb"<script>(.*?)</script>", html_bytes, re.S)]
    return ("default-src 'none'; script-src " + " ".join(f"'sha256-{h}'" for h in hashes) + "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


class BoundedServer(ThreadingHTTPServer):
    """Plafonne le nombre de connexions simultanées (un client lent ou malveillant ne peut pas épuiser les threads)."""
    _sem = threading.BoundedSemaphore(400)

    def process_request(self, request, client_address):
        if not self._sem.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._sem.release()


class Handler(BaseHTTPRequestHandler):
    timeout = 12                 # une connexion qui ne parle pas est fermée (anti « slowloris »)
    server_version = "relais"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send_response(self, code, message=None):
        self._sent = set()
        super().send_response(code, message)

    def send_header(self, keyword, value):
        self._sent.add(keyword.lower())
        super().send_header(keyword, value)

    def end_headers(self):
        for k, v in SEC_DEFAULTS.items():
            if k.lower() not in self._sent:
                BaseHTTPRequestHandler.send_header(self, k, v)
        super().end_headers()

    def _ok_host(self):
        h = self.headers.get("Host", "").lower().strip()
        host = h.split("]")[0] + "]" if h.startswith("[") else h.split(":")[0]
        return host in ALLOWED_HOSTS

    def _ip(self):
        if TRUST_PROXY:
            xf = self.headers.get("X-Forwarded-For", "")
            if xf:
                return xf.split(",")[0].strip()
        return self.client_address[0]

    def _token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k in ("__Host-hub_session", "hub_session"):
                return v
        return ""

    def _authed(self):
        """Utilisateur de la session ({"name","role"}) ; en usage local sans authentification : l'utilisateur local (admin)."""
        if not AUTH.enabled:
            return {"name": "local", "role": "admin"}
        return AUTH.valid(self._token())

    def _secure(self):
        return SECURE_COOKIE or (TRUST_PROXY and self.headers.get("X-Forwarded-Proto", "") == "https")

    def _login_page(self):
        body = page("login.html")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp_for(body))
        self.end_headers()
        self.wfile.write(body)

    def _session_ok(self, tok):
        self.send_response(200)
        out = json.dumps({"ok": True}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        if self._secure():   # préfixe __Host- : le navigateur refuse tout cookie qui ne serait pas Secure, sans Domain et à la racine
            self.send_header("Set-Cookie", f"__Host-hub_session={tok}; HttpOnly; SameSite=Strict; Path=/; Secure; Max-Age={authmod.SESSION_TTL}")
        else:
            self.send_header("Set-Cookie", f"hub_session={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={authmod.SESSION_TTL}")
        self.end_headers()
        self.wfile.write(out)

    def _page(self, name):
        body = page(name)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp_for(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":   # sonde de santé (Docker) : aucune donnée
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._ok_host():
            return self._json({"error": "host refusé"}, 403)
        u = urlparse(self.path)
        if u.path == "/join" and AUTH.enabled:   # page d'inscription par invitation (le jeton est dans le fragment « # » : il ne part jamais au serveur ni dans les journaux)
            return self._page("join.html")
        user = self._authed()
        if u.path == "/login":
            if user and AUTH.enabled:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            return self._login_page()
        if not user:
            if u.path in ("/", "/index.html"):
                if "RelaisApp" in self.headers.get("User-Agent", ""):   # l'application Android va directement à la connexion
                    return self._login_page()
                body = page("index.html").replace(b"<body>", b'<body data-public="1">', 1)   # page d'accueil publique : aucune donnée, seulement l'interface statique
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Security-Policy", csp_for(body))
                self.end_headers()
                self.wfile.write(body)
                return
            return self._json({"error": "authentification requise"}, 401)
        REQ.user = user
        try:
            self._route_get(u)
        finally:
            REQ.user = None

    def _route_get(self, u):
        if u.path in ("/", "/index.html"):
            body = page("index.html")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", csp_for(body))
            self.end_headers()
            self.wfile.write(body)
        elif u.path.startswith("/linkimg/"):
            serve_linkimg(self, u.path[len("/linkimg/"):])
        elif u.path.startswith("/media/"):
            qs = parse_qs(u.query)
            serve_media(self, u.path[len("/media/"):], "p" in qs, "dl" in qs)
        elif u.path == "/api/state":
            self._json(api_state())
        elif u.path == "/api/stats":
            self._json(api_stats())
        elif u.path == "/api/avatar":
            akey = parse_qs(u.query).get("key", [""])[0]
            data = avatar_bytes(akey) if own_chat(akey) else None
            if not data:
                return self._json({"error": "pas de photo"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg" if data[:3] == b"\xff\xd8\xff" else
                             "image/png" if data[:4] == b"\x89PNG" else "image/webp" if data[8:12] == b"WEBP" else "application/octet-stream")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/api/accounts/login/status":
            info = LOGIN.get(_lkey(cur_name()))
            self._json({"state": info["state"], "error": info["error"], "name": info["name"], "reused": info["reused"], "remote": info.get("remote", False), "phase": info.get("phase", "")} if info else {"state": "none"})
        elif u.path == "/relais.apk":
            f = HERE.parent / "dist" / "relais.apk"
            try:
                data = f.read_bytes()
            except OSError:
                return self._json({"error": "application indisponible"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Disposition", 'attachment; filename="Relais.apk"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/relais-connect.zip":
            host = self.headers.get("Host", "")
            data = ext_zip(("https://" if self._secure() else "http://") + host)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="relais-connect.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/api/accounts/login/frame":
            info = LOGIN.get(_lkey(cur_name()))
            if not info or not info.get("remote"):
                return self._json({"error": "aucune connexion en cours"}, 404)
            try:
                last = int(parse_qs(u.query).get("n", ["0"])[0])
            except ValueError:
                last = 0
            f = info["dir"] / "frame.jpg"
            for _ in range(25):   # attente d'une image plus récente (≤ 2,5 s) puis 204
                try:
                    st = f.stat().st_mtime_ns
                    if st > last:
                        data = f.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("X-N", str(st))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                except OSError:
                    pass
                if info["state"] not in ("starting", "waiting_login"):
                    break
                time.sleep(0.1)
            self.send_response(204)
            self.send_header("X-N", str(last))
            self.end_headers()
        elif u.path == "/api/chat":
            ckey = parse_qs(u.query).get("key", [""])[0]
            r = api_chat(ckey) if own_chat(ckey) else None
            self._json(r if r else {"error": "inconnu"}, 200 if r else 404)
        else:
            self._json({"error": "introuvable"}, 404)

    def do_POST(self):
        # protection CSRF : en-tête personnalisé (interdit en cross-origin sans préflight) + hôte local
        if not self._ok_host() or self.headers.get("X-Hub") != "1":
            return self._json({"error": "refusé"}, 403)
        path = urlparse(self.path).path
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
            body = json.loads(self.rfile.read(n) or b"{}")
            if path == "/api/login":
                if not AUTH.enabled:
                    return self._json({"error": "authentification non activée"}, 400)
                try:
                    tok = AUTH.login(body.get("username"), body.get("password"), self._ip())
                except PermissionError as ex:
                    return self._json({"error": str(ex)}, 429)
                if not tok:
                    log("warn", f"Échec de connexion au hub (identifiant « {clean(body.get('username'))} », adresse {clean(self._ip(), 45)})")
                    return self._json({"error": "Identifiant ou mot de passe incorrect."}, 401)
                log("info", f"Connexion au hub réussie (« {clean(body.get('username'))} », adresse {clean(self._ip(), 45)})")
                return self._session_ok(tok)
            if path == "/api/accounts/import_ext":
                return self._json(ext_import(body.get("code"), body.get("cookies"), self._ip()))
            if path == "/api/join":
                if not AUTH.enabled:
                    return self._json({"error": "authentification non activée"}, 400)
                name = str(body.get("username") or "").strip().lower()
                try:
                    AUTH.redeem_invite(body.get("token"), name, body.get("password"), self._ip())
                except PermissionError as ex:
                    return self._json({"error": str(ex)}, 429)
                except ValueError as ex:
                    return self._json({"error": str(ex)}, 400)
                log("info", f"Nouvel utilisateur « {clean(name)} » inscrit par invitation (adresse {clean(self._ip(), 45)})")
                tok = AUTH.login(name, body.get("password"), self._ip())
                return self._session_ok(tok) if tok else self._json({"ok": True})
            user = self._authed()
            if not user:
                return self._json({"error": "authentification requise"}, 401)
            if path == "/api/logout":
                AUTH.logout(self._token())
                self.send_response(200)
                out = b'{"ok": true}'
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.send_header("Set-Cookie", "hub_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.send_header("Set-Cookie", "__Host-hub_session=; HttpOnly; SameSite=Strict; Path=/; Secure; Max-Age=0")
                self.end_headers()
                self.wfile.write(out)
                return
            REQ.user = user
            try:
                self._json(post(path, body))
            finally:
                REQ.user = None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError, sqlite3.Error):
            self._json({"error": "requête invalide"}, 400)
        except Exception as ex:
            log("error", f"Erreur de requête {path} : {type(ex).__name__}: {str(ex)[:120]}")
            self._json({"error": "erreur interne"}, 500)
