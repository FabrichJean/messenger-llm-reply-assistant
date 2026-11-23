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
