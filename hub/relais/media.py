"""Pièces jointes : téléchargement sûr, détection du type réel, règles d'affichage.

Rien ici ne dépend du hub : on peut tester ces fonctions seules.
"""
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Les liens de pièces jointes de Messenger pointent vers les CDN de Meta. Tout autre hôte est refusé (pas de SSRF).
_DEFAULT_HOSTS = ("fbcdn.net", "facebook.com", "fbsbx.com", "messenger.com", "cdninstagram.com", "fb.com")
ALLOWED_HOSTS = _DEFAULT_HOSTS + tuple(h.strip() for h in os.environ.get("HUB_MEDIA_ALLOW_HOSTS", "").split(",") if h.strip())
ALLOW_HTTP = os.environ.get("HUB_MEDIA_ALLOW_HTTP") == "1"   # tests uniquement

MB = 1024 * 1024
MAX_BYTES = {"image": 15 * MB, "gif": 25 * MB, "sticker": 8 * MB, "link": 8 * MB, "audio": 25 * MB, "video": 60 * MB, "file": 60 * MB}
CACHE_CAP = 1024 * MB   # par compte : au-delà, on supprime les plus anciens (ils se retéléchargent à la demande)

# types affichés directement dans la page ; tout le reste est proposé en téléchargement
INLINE = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif",
          "video/mp4", "video/webm", "video/quicktime",
          "audio/mpeg", "audio/mp4", "audio/ogg", "audio/webm", "audio/wav", "audio/aac"}


def host_allowed(url):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme != "https" and not (ALLOW_HTTP and u.scheme == "http"):
        return False
    if u.username or u.password or not u.hostname:
        return False
    h = u.hostname.lower()
    if re.fullmatch(r"[\d.]+|[0-9a-f:]+", h) and not ALLOW_HTTP:   # adresses IP : refusées
        return False
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl):
            raise urllib.error.URLError(f"redirection vers un hôte non autorisé : {urlparse(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, max_bytes, timeout=25, ctx=None):
    """Télécharge sans cookies ni identifiants, en refusant tout hôte hors liste et tout fichier trop gros."""
    if not host_allowed(url):
        raise ValueError("adresse de pièce jointe non autorisée")
    handlers = [_Redirect()]
    if ctx is not None:   # certificats racine : ceux que le hub a déjà choisis (Python seul n'en a pas toujours)
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with opener.open(req, timeout=timeout) as r:
        declared = r.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ValueError("fichier trop gros")
        data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("fichier trop gros")
        return data, (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()


def sniff(data, fallback=""):
    """Type réel d'après les premiers octets (on ne fait jamais confiance au type annoncé)."""
    h = data[:16]
    if h[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if data[4:8] == b"ftyp":
        return "video/quicktime" if data[8:12] == b"qt  " else ("audio/mp4" if data[8:12] in (b"M4A ", b"M4B ") else "video/mp4")
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if h[:4] == b"OggS":
        return "audio/ogg"
    if h[:3] == b"ID3" or h[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if h[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if h[:4] == b"%PDF":
        return "application/pdf"
    if h[:4] == b"PK\x03\x04":
        return "application/zip"
    return fallback or "application/octet-stream"


def serve_type(kind, data_head, declared=""):
    """(type à envoyer, affichage direct ?) : seuls des types médias sûrs sont affichés dans la page."""
    real = sniff(data_head, "")   # le type annoncé n'est jamais utilisé : seul le contenu reconnu peut être affiché
    return real, real in INLINE


def safe_name(name, fallback="fichier"):
    n = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]", "_", str(name or "")).strip(". ")[:100]
    return n or fallback


def clean(s, n):
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(s or "")).strip()[:n]


def web_url(s, n=1000):
    """Lien cliquable : http(s) uniquement."""
    s = str(s or "").strip()[:n]
    return s if re.match(r"^https?://[^\s]+$", s, re.I) else ""


def evict(dirpath, cap=CACHE_CAP):
    """Supprime les fichiers les plus anciens quand le dossier dépasse sa limite."""
    try:
        files = [(f.stat().st_mtime, f.stat().st_size, f) for f in os.scandir(dirpath) if f.is_file()]
    except OSError:
        return 0
    total = sum(s for _, s, _ in files)
    if total <= cap:
        return 0
    removed = 0
    for _, size, f in sorted(files, key=lambda t: t[0]):
        if total <= cap * 0.9:
            break
        try:
            os.unlink(f.path)
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- aperçus de liens (pages publiques)
import html as _html
import http.client
import ipaddress
import socket
import ssl as _ssl
from urllib.parse import urljoin

ALLOW_LOCAL = os.environ.get("HUB_PREVIEW_ALLOW_LOCAL") == "1"   # tests uniquement
PREVIEW_UA = "Mozilla/5.0 (compatible; RelaisLinkPreview/1.0)"
URL_RE = re.compile(r"https?://[^\s<>\"' ]+", re.I)


def urls_in(text, limit=2):
    """Liens http(s) d'un message (sans la ponctuation finale), dédoublonnés."""
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?)]}»”'")
        if len(u) <= 600 and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def _is_public(ip):
    """Vrai seulement pour une adresse routable sur Internet (liste d'autorisation, pas d'interdits à énumérer).
    Exclut notamment 100.64.0.0/10 (réseau partagé : Tailscale, métadonnées de certains clouds), qu'une liste d'interdits oublie."""
    if ip.version == 6:
        for inner in (ip.ipv4_mapped, ip.sixtofour):                      # IPv4 embarquée : on juge l'adresse IPv4 qu'elle contient
            if inner is not None:
                return _is_public(inner)
        if ip.teredo is not None:
            return all(_is_public(x) for x in ip.teredo)
        if ip in _NAT64:
            return _is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return ip.is_global and not ip.is_multicast


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public_ips(host, port):
    """Adresses du nom d'hôte, toutes devant être publiques (jamais le réseau local, l'hôte lui-même ou un service interne)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips = []
    for fam, _t, _p, _c, sa in infos:
        ip = ipaddress.ip_address(sa[0])
        if not _is_public(ip) and not ALLOW_LOCAL:
            raise ValueError("adresse non publique refusée")
        ips.append(sa[0])
    if not ips:
        raise ValueError("hôte introuvable")
    return ips


class _Pinned(http.client.HTTPSConnection):
    """Se connecte à l'adresse IP déjà vérifiée (aucune seconde résolution DNS possible entre le contrôle et l'usage)."""
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def fetch_public(url, max_bytes, timeout=10, ctx=None, accept="*/*", hops=4, cookie="", cookie_hosts=()):
    """GET d'une page publique : http(s) seulement, ports 80/443, adresses publiques, redirections revalidées, taille limitée, sans cookies."""
    cur = url
    for _ in range(hops + 1):
        u = urlparse(cur)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            raise ValueError("adresse refusée")
        port = u.port or (443 if u.scheme == "https" else 80)
        if port not in (80, 443) and not ALLOW_LOCAL:
            raise ValueError("port refusé")
        ip = _public_ips(u.hostname, port)[0]
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        if u.scheme == "https":
            conn = _Pinned(u.hostname, ip, port=port, timeout=timeout, context=ctx or _ssl.create_default_context())
        else:
            conn = _PinnedHTTP(u.hostname, ip, port=port, timeout=timeout)
        try:
            hdrs = {"Host": u.netloc.split("@")[-1], "User-Agent": PREVIEW_UA, "Accept": accept, "Accept-Language": "fr,en;q=0.8"}
            h = u.hostname.lower()
            if cookie and (u.scheme == "https" or ALLOW_LOCAL) and any(h == d or h.endswith("." + d) for d in cookie_hosts):   # la session ne part QUE vers ces domaines, à chaque étape
                hdrs["Cookie"] = cookie
            conn.request("GET", path, headers=hdrs)
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                cur = urljoin(cur, r.getheader("Location"))
                continue
            if r.status != 200:
                raise ValueError(f"réponse {r.status}")
            declared = r.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                data = r.read(max_bytes)   # grosse page : on ne lit que le début (les balises utiles s'y trouvent)
            else:
                data = r.read(max_bytes + 1)[:max_bytes]
            return data, (r.getheader("Content-Type") or "").split(";")[0].strip().lower(), cur, r.getheader("Content-Type") or ""
        finally:
            conn.close()
    raise ValueError("trop de redirections")


def _meta(html, keys):
    for k in keys:
        for pat in (r'<meta[^>]+(?:property|name)\s*=\s*["\']%s["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']' % re.escape(k),
                    r'<meta[^>]+content\s*=\s*["\']([^"\']*)["\'][^>]*?(?:property|name)\s*=\s*["\']%s["\']' % re.escape(k)):
            m = re.search(pat, html, re.I | re.S)
            if m and m.group(1).strip():
                return _html.unescape(m.group(1)).strip()
    return ""


def parse_preview(raw, ctype_header, base):
    """Titre, description, site et image (Open Graph / Twitter / balises HTML) d'une page. Tout est du texte brut, borné et nettoyé."""
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype_header or "", re.I) or re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4096], re.I)
    if m:
        charset = m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")
    html = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", html, flags=re.S | re.I)
    title = _meta(html, ("og:title", "twitter:title"))
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = _html.unescape(m.group(1)).strip() if m else ""
    descr = _meta(html, ("og:description", "twitter:description", "description"))
    site = _meta(html, ("og:site_name",))
    img = _meta(html, ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"))
    img = urljoin(base, img) if img else ""
    og = bool(_meta(html, ("og:title", "twitter:title")))
    t = clean(re.sub(r"\s+", " ", title), 200)
    if not og and re.search(r"connect(ez|er)[- ]vous|inscrivez|log ?in|log into|sign ?(in|up)|accept cookies|cookies", t, re.I):
        return {"title": "", "descr": "", "site": "", "image": "", "wall": True}   # page de connexion / de consentement : aucune information utile
    return {"title": t, "descr": clean(re.sub(r"\s+", " ", descr), 300),
            "site": clean(site, 80), "image": web_url(img, 1000)}
