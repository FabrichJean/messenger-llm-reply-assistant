#!/usr/bin/env python3
"""Hub Messenger Lite : interface web + LLM (Claude CLI) pour les contacts choisis.

- Lance un processus `messenger-lite` par compte (accounts.json) et lit ses événements.
- Le LLM ne répond QU'AUX CONTACTS ACTIVÉS (liste blanche, désactivé par défaut).
- Claude est appelé sans aucun outil, dans un dossier vide (les messages reçus sont du texte non fiable).
- Écoute uniquement sur 127.0.0.1. Sur un VPS : accès par tunnel SSH.

Lancement :  python3 hub.py        puis ouvrir http://127.0.0.1:8787  (aucun compte au départ : « 👤 Comptes » pour en ajouter)
"""
import base64
import hashlib
import secrets
import hmac
import re
import shutil
import tempfile
import sys
import json
import os
import random
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, parse_qs, urlparse

HERE = Path(__file__).resolve().parent
os.umask(0o077)   # tout fichier créé (base, cookies, pièces jointes, sessions) n'est lisible que par ce processus
sys.path.insert(0, str(HERE))
import security  # noqa: E402
import media  # noqa: E402
import auth as authmod  # noqa: E402
import humanize as hz
import memory as mem_mod  # noqa: E402
DATA = Path(os.environ.get("HUB_DATA", HERE))
PORT = int(os.environ.get("HUB_PORT", "8787"))
BIND = os.environ.get("HUB_BIND", "127.0.0.1")
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"} | {h.strip().lower() for h in os.environ.get("HUB_ALLOWED_HOSTS", "").split(",") if h.strip()}
TRUST_PROXY = os.environ.get("HUB_TRUST_PROXY") == "1"        # derrière Caddy / nginx : on lit X-Forwarded-*
SECURE_COOKIE = os.environ.get("HUB_SECURE_COOKIE") == "1"
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
DATA.mkdir(parents=True, exist_ok=True)
SANDBOX = DATA / "sandbox"
SANDBOX.mkdir(exist_ok=True)
AUTH = authmod.Auth(DATA, os.environ.get("HUB_PASSWORD", ""), os.environ.get("HUB_ADMIN_USER", "admin"))

acc_file = DATA / "accounts.json"
ACCOUNT_CFG = json.loads(acc_file.read_text()) if acc_file.exists() else []   # aucun compte par défaut : on les ajoute depuis l'interface

# ---------------------------------------------------------------- base de données
L = threading.RLock()
DB = sqlite3.connect(DATA / "hub.db", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.executescript("""
CREATE TABLE IF NOT EXISTS chats(
  key TEXT PRIMARY KEY, account TEXT, name TEXT DEFAULT '', last_ts INTEGER DEFAULT 0, last_text TEXT DEFAULT '',
  route TEXT DEFAULT 'classic', jid TEXT DEFAULT '', thread INTEGER DEFAULT 0, is_group INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 0, enabled_at INTEGER DEFAULT 0, mode TEXT DEFAULT 'auto',
  instructions TEXT DEFAULT '', max_per_hour INTEGER DEFAULT 10, delay_s INTEGER DEFAULT 6, attention INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT, chat_key TEXT, ts INTEGER, sender TEXT, text TEXT, src TEXT, PRIMARY KEY(id, chat_key));
CREATE INDEX IF NOT EXISTS msg_chat_ts ON messages(chat_key, ts);
CREATE TABLE IF NOT EXISTS attachments(
  id TEXT PRIMARY KEY, account TEXT, chat_key TEXT, msg_id TEXT, idx INTEGER DEFAULT 0, kind TEXT, name TEXT DEFAULT '',
  mime TEXT DEFAULT '', size INTEGER DEFAULT 0, w INTEGER DEFAULT 0, h INTEGER DEFAULT 0, dur INTEGER DEFAULT 0,
  url TEXT DEFAULT '', preview TEXT DEFAULT '', action TEXT DEFAULT '', title TEXT DEFAULT '', subtitle TEXT DEFAULT '',
  descr TEXT DEFAULT '', site TEXT DEFAULT '', blob TEXT DEFAULT '', mtype TEXT DEFAULT '', source TEXT DEFAULT '', ts INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS att_msg ON attachments(chat_key, msg_id);
CREATE TABLE IF NOT EXISTS link_previews(
  h TEXT PRIMARY KEY, url TEXT, status TEXT DEFAULT '', title TEXT DEFAULT '', descr TEXT DEFAULT '', site TEXT DEFAULT '', image INTEGER DEFAULT 0, ts INTEGER DEFAULT 0, auth INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS llm_usage(
  ts INTEGER, kind TEXT, model TEXT, input INTEGER DEFAULT 0, cache_read INTEGER DEFAULT 0, cache_write INTEGER DEFAULT 0, output INTEGER DEFAULT 0, cost REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS usage_ts ON llm_usage(ts);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_key TEXT, text TEXT, created INTEGER, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS contacts(account TEXT, id INTEGER, name TEXT, PRIMARY KEY(account, id));
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS account_settings(account TEXT, k TEXT, v TEXT, PRIMARY KEY(account, k));
CREATE TABLE IF NOT EXISTS security_events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, chat_key TEXT, kind TEXT, detail TEXT);
""")
for _tbl, _col in (("chats", "pic TEXT DEFAULT ''"), ("contacts", "pic TEXT DEFAULT ''"), ("chats", "kind INTEGER DEFAULT 0"), ("chats", "lookup_ts INTEGER DEFAULT 0"), ("chats", "attention_note TEXT DEFAULT ''"),
                   ("messages", "edited INTEGER DEFAULT 0"), ("messages", "deleted INTEGER DEFAULT 0"),
                   ("messages", "local_edit INTEGER DEFAULT 0"), ("messages", "orig_text TEXT DEFAULT ''"),
                   ("chats", "takeover_off INTEGER DEFAULT 0"), ("chats", "unmute_ts INTEGER DEFAULT 0"),
                   ("chats", "trusted INTEGER DEFAULT 0"), ("messages", "auto INTEGER DEFAULT 0"), ("chats", "pinned INTEGER DEFAULT 0"), ("link_previews", "auth INTEGER DEFAULT 0"), ("llm_usage", "account TEXT DEFAULT ''"), ("chats", "memory TEXT DEFAULT ''"), ("chats", "memory_ts INTEGER DEFAULT 0")):
    try:
        DB.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col}")
    except sqlite3.OperationalError:
        pass  # colonne déjà présente
# anciens aperçus qui n'étaient en fait que des pages de connexion : on les oublie pour les refaire proprement
DB.execute("DELETE FROM link_previews WHERE auth=0 AND (title LIKE '%Connectez-vous%' OR title LIKE '%inscrivez-vous%' OR title LIKE '%Log in%' OR title LIKE '%log into%' OR title LIKE '%Sign up%')")
DB.commit()
(DATA / "avatars").mkdir(exist_ok=True)


def q(sql, args=()):
    with L:
        return [dict(r) for r in DB.execute(sql, args).fetchall()]


def x(sql, args=()):
    with L:
        cur = DB.execute(sql, args)
        DB.commit()
        return cur


SETTING_DEFAULTS = {
    "paused": "0", "model": "sonnet", "owner": "le propriétaire du compte", "persona": "",
    "max_per_hour_global": "60", "takeover_min": "10",
    "style_profile": "", "style_cross": "1", "style_auto": "1", "style_n": "0", "late_reply_min": "120", "sync_s": "120", "judge": "1", "security_level": "strict", "classifier": "1", "attack_mode": "decoy", "link_preview": "1", "link_preview_fb": "1", "typing": "1", "read_delay": "10", "token_mode": "normal",
}


PRIVATE_KEYS = ("owner", "persona", "style_profile", "style_n")   # jamais hérités des valeurs générales (celles de l'administrateur) en mode multi-utilisateurs


def setting(k, account=None):
    """Valeur d'un réglage : la valeur propre au compte si elle existe, sinon la valeur générale, sinon la valeur par défaut."""
    if account:
        r = q("SELECT v FROM account_settings WHERE account=? AND k=?", (account, k))
        if r:
            return r[0]["v"]
        if AUTH.enabled and k in PRIVATE_KEYS:
            return SETTING_DEFAULTS[k]
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    return r[0]["v"] if r else SETTING_DEFAULTS[k]


def set_setting(k, v, account=None):
    if account:
        x("INSERT INTO account_settings(account,k,v) VALUES(?,?,?) ON CONFLICT(account,k) DO UPDATE SET v=excluded.v", (account, k, str(v)))
    else:
        x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def is_paused(account=None):
    """La pause générale prime : si elle est active, tous les comptes sont en pause ; chaque compte peut aussi avoir la sienne."""
    return setting("paused") == "1" or (bool(account) and setting("paused", account) == "1")


def default_account():
    """Premier compte s'il y en a (sinon None). Il n'existe pas de compte « principal » : tous les comptes sont égaux."""
    return next(iter(ACCOUNTS), None)


def acct_of(key):
    """Compte d'une conversation (clé « compte:identifiant »)."""
    return str(key).split(":", 1)[0]


# ---------------------------------------------------------------- utilisateurs : contexte de la requête en cours
REQ = threading.local()


def cur():
    """Utilisateur de la requête en cours ({"name","role"}), ou None (tâche de fond)."""
    return getattr(REQ, "user", None)


def cur_name():
    u = cur()
    return u["name"] if (u and AUTH.enabled) else None


def is_admin():
    u = cur()
    return bool(u and u["role"] == "admin")


def mine():
    """Noms des comptes Messenger que l'utilisateur courant possède (sans authentification activée : usage local, tous les comptes)."""
    if not AUTH.enabled:
        return set(ACCOUNTS)
    u = cur()
    return {n for n, a in ACCOUNTS.items() if u and a.owner == u["name"]}


def own_chat(key):
    if not isinstance(key, str):
        return False
    r = q("SELECT account FROM chats WHERE key=?", (key,))
    return bool(r) and r[0]["account"] in mine()


LOG = deque(maxlen=300)
_LOGACC = re.compile(r"^\[([a-z0-9_-]{2,20})\]")


def clean(v, n=32):
    """Texte d'un utilisateur sûr pour un journal (pas de saut de ligne ni de caractère de contrôle)."""
    return re.sub(r"[^a-zA-Z0-9_.@-]", "?", str(v or ""))[:n]


def log(level, text, chat=None, acct=None):
    if not acct:
        acct = acct_of(chat) if chat else None
        if not acct:
            m = _LOGACC.match(text)
            acct = m.group(1) if m else None
    entry = {"ts": int(time.time() * 1000), "level": level, "text": text, "chat": chat, "acct": acct}
    LOG.append(entry)
    try:
        print(time.strftime("%H:%M:%S"), level, text, flush=True)
    except (OSError, ValueError):
        pass  # disque plein ou sortie fermée : on ne casse jamais le serveur pour un journal
    try:  # journal persistant (jamais le texte des messages, seulement les décisions)
        with open(DATA / "hub.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {level} {('[' + chat + '] ') if chat else ''}{text}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- comptes (processus messenger-lite)
class Account:
    def __init__(self, cfg):
        self.name, self.dir, self.bin = cfg["name"], cfg["dir"], cfg["bin"]
        self.owner = cfg.get("owner")               # utilisateur du hub à qui appartient ce compte (isolation multi-utilisateurs)
        self.label = str(cfg.get("label") or "")   # nom d'affichage = vrai nom du profil Messenger (la clé interne `name` ne change jamais)
        self.base_args = list(cfg.get("args", []))
        self.args = list(self.base_args)
        self.proc = None
        self.lock = threading.Lock()
        self.state = {"running": False, "classic": False, "e2ee": False, "note": ""}
        self.stop = False
        self.thread = None
        self.down_since = 0

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name=f"acct-{self.name}")
        self.thread.start()

    def loop(self):
        backoff = 3
        while not self.stop:
            t0 = time.time()
            try:
                err = open(DATA / f"{self.name}.err", "wb")
                launch_args = list(self.args)
                if "-register-e2ee" in launch_args:
                    self.args = list(self.base_args)  # l'enregistrement de l'appareil n'est tenté qu'UNE fois, jamais en boucle
                cenv = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TZ", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")}
                self.proc = subprocess.Popen([self.bin, *launch_args], cwd=self.dir, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1, env=cenv)
                self.state.update(running=True, note="")
                log("info", f"[{self.name}] client démarré")
                for line in self.proc.stdout:
                    try:
                        handle_event(self, json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:  # ne jamais tuer la boucle de lecture
                        log("error", f"[{self.name}] événement ignoré: {e!r}")
                self.proc.wait()
            except FileNotFoundError:
                self.state["note"] = f"binaire introuvable: {self.bin}"
            except Exception as e:
                self.state["note"] = repr(e)
            self.state.update(running=False, classic=False, e2ee=False)
            if self.stop:
                break
            try:   # session refusée par Messenger : inutile de réessayer en boucle (ça n'arrange rien et peut alerter Meta)
                tail = (DATA / f"{self.name}.err").read_text(errors="replace")[-600:]
            except OSError:
                tail = ""
            if "user id in initial data is zero" in tail or "access token is no longer valid" in tail:
                self.state.update(expired=True, note="session expirée ou refusée : reconnecte ce compte (👤 Comptes)")
                log("warn", f"[{self.name}] session refusée par Messenger : reconnecte le compte (arrêt des tentatives)")
                break
            if "/privacy/consent" in tail or "/checkpoint" in tail or "two_step_verification" in tail or "/login/?next" in tail:
                # Meta demande une action à la personne (consentement, vérification de sécurité) : inutile de réessayer depuis le serveur, ça n'arrange rien
                self.state.update(expired=True, note="Meta demande une validation (consentement ou vérification de sécurité). Reconnecte ce compte depuis l'application : accepte la demande qui s'affiche, puis le compte repart tout seul.")
                log("warn", f"[{self.name}] Meta demande une validation (consentement ou vérification) : arrêt des tentatives, reconnexion nécessaire")
                break
            self.state["expired"] = False
            backoff = 3 if time.time() - t0 > 60 else min(backoff * 2, 120)
            log("warn", f"[{self.name}] client arrêté, relance dans {backoff}s {self.state['note']}")
            time.sleep(backoff)

    def send(self, cmd):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return False
            try:
                self.proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
                return True
            except Exception:
                return False

    def shutdown(self):
        self.stop = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def _fix_cfg(c):
    """Un accounts.json venu d'une autre machine contient des chemins qui n'existent pas ici : on les recalcule."""
    root = Path(os.environ.get("HUB_ACCOUNTS_ROOT", HERE.parent / "accounts"))
    cli = os.environ.get("HUB_CLIENT_BIN", str(HERE.parent / "messenger-lite"))
    c = dict(c)
    if not Path(c["dir"]).exists() and (root / c["name"]).exists():
        c["dir"] = str(root / c["name"])
    if not Path(c["bin"]).exists():
        c["bin"] = cli
    return c


ACCOUNTS = {c["name"]: Account(_fix_cfg(c)) for c in ACCOUNT_CFG}
ACCOUNTS_ROOT = Path(os.environ.get("HUB_ACCOUNTS_ROOT", HERE.parent / "accounts"))
CLIENT_BIN = os.environ.get("HUB_CLIENT_BIN", str(HERE.parent / "messenger-lite"))
REMOTE_LOGIN = os.environ.get("HUB_LOGIN_REMOTE") == "1"   # serveur sans écran : navigateur distant affiché dans une fenêtre modale du hub
LOGIN_PY = Path(os.environ.get("HUB_LOGIN_PY") or (HERE.parent / ".venv" / "bin" / "python"))
if REMOTE_LOGIN and not LOGIN_PY.exists():
    LOGIN_PY = Path(sys.executable)
LOGIN_SCRIPT = HERE.parent / "login_browser.py"
LOGIN_ENV_KEEP = ("PATH", "HOME", "TZ", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "LOGIN_NO_SANDBOX", "LOGIN_CHANNEL", "LOGIN_TEST_HOST", "DISPLAY", "SSL_CERT_FILE", "SSL_CERT_DIR")
LOGIN_KEYS = ("click", "text", "key", "scroll", "login")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,19}$")
LOGIN = {}   # nom -> {"proc","state","error","user_id","started"}


def save_accounts():
    """Liste des comptes sur disque (sans l'indicateur temporaire d'enregistrement)."""
    data = [{"name": a.name, "label": a.label, "owner": a.owner, "dir": a.dir, "bin": a.bin, "args": a.base_args} for a in ACCOUNTS.values()]
    tmp = DATA / "accounts.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, DATA / "accounts.json")


def add_account(name, dirpath, owner=None):
    cfg = {"name": name, "dir": str(dirpath), "bin": CLIENT_BIN, "args": [], "owner": owner}
    acct = Account(cfg)
    ACCOUNTS[name] = acct
    save_accounts()
    acct.start()
    log("info", f"Compte « {name} » ajouté", acct=name)
    return acct


def _migrate_owners():
    """Tout compte sans propriétaire valide est rattaché à l'utilisateur du même nom, sinon au premier administrateur."""
    if not AUTH.enabled:
        return
    adm = (AUTH.admins() or [None])[0]
    changed = False
    for a in ACCOUNTS.values():
        if not a.owner or not AUTH.exists(a.owner):
            a.owner = a.name if AUTH.exists(a.name) else adm
            changed = True
    if changed:
        save_accounts()


_migrate_owners()


def has_registered_device(dirpath):
    """Vrai seulement si un appareil chiffré est VRAIMENT enregistré (le fichier e2ee.db existe dès le premier démarrage du client, même vide)."""
    f = Path(dirpath) / "e2ee.db"
    if not f.exists():
        return False
    try:
        c = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=2)
        try:
            return c.execute("SELECT COUNT(*) FROM whatsmeow_device").fetchone()[0] > 0
        finally:
            c.close()
    except sqlite3.Error:
        return False


def account_dir(name):
    d = ACCOUNTS_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def parse_curl_cookies(text):
    """Cookies d'une commande « Copy as cURL » (ou d'un en-tête Cookie collé). Les valeurs ne sont jamais affichées."""
    m = re.search(r"""(?:-b|--cookie)\s+(['"])(.*?)\1""", text, re.S) or re.search(r"""-H\s+(['"])\s*cookie:\s*(.*?)\1""", text, re.S | re.I)
    header = m.group(2) if m else text
    jar = {}
    for part in re.split(r";\s*", header.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip().strip("'\"")
    keep = ("c_user", "xs", "datr", "sb", "fr", "wd", "presence", "dpr", "oo")
    if not all(jar.get(k) for k in ("c_user", "xs", "datr")):
        return None
    return {k: jar[k] for k in keep if jar.get(k)}


def write_cookies(name, jar):
    d = account_dir(name)
    fd = os.open(d / "cookies.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(jar, f, indent=2)
    return d


def find_account_name(c_user):
    """Nom du dossier déjà associé à ce compte Messenger (même c_user), même si le compte a été retiré de l'application."""
    for a in ACCOUNTS.values():
        try:
            if json.loads((Path(a.dir) / "cookies.json").read_text()).get("c_user") == c_user:
                return a.name
        except (OSError, ValueError):
            pass
    if ACCOUNTS_ROOT.is_dir():
        for d in sorted(ACCOUNTS_ROOT.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            try:
                if json.loads((d / "cookies.json").read_text()).get("c_user") == c_user:
                    return d.name
            except (OSError, ValueError):
                pass
    return None


def new_account_name(c_user):
    """Nom automatique pour un nouveau compte (l'utilisateur n'a rien à saisir)."""
    digits = re.sub(r"\D", "", c_user)
    for n in range(8, len(digits) + 1):
        name = "fb-" + digits[-n:]
        if NAME_RE.match(name) and name not in ACCOUNTS and not (ACCOUNTS_ROOT / name).exists():
            return name
    return "fb-" + digits[-12:]


def check_session(jar):
    """Vérifie, avec le vrai client, que Messenger accepte ces cookies (dossier temporaire : aucun compte n'est touché)."""
    if os.environ.get("HUB_SKIP_CHECK") == "1":
        return
    d = Path(tempfile.mkdtemp(prefix=".check-", dir=str(ACCOUNTS_ROOT) if ACCOUNTS_ROOT.is_dir() else None))
    try:
        os.chmod(d, 0o700)
        fd = os.open(d / "cookies.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(jar, f)
        try:
            r = subprocess.run([CLIENT_BIN, "-check", "-e2ee=false"], cwd=str(d), capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise ValueError("Messenger ne répond pas : réessaie dans un instant")
        except OSError as ex:
            raise ValueError(f"client introuvable : {ex}")
        if r.returncode != 0 or "ok" not in r.stdout:
            err = (r.stderr or "").strip().splitlines()[-1:] or [""]
            log("warn", f"Session refusée par Messenger : {err[0][:200]}")
            if "/privacy/consent" in (r.stderr or "") or "/checkpoint" in (r.stderr or ""):
                raise ValueError("Messenger demande d'abord une validation (écran de consentement ou de sécurité).")
            raise ValueError("Messenger a refusé cette session (connexion pas terminée ?). Recommence en allant jusqu'à ta liste de conversations sur messenger.com.")
    finally:
        shutil.rmtree(d, ignore_errors=True)


CONNECT_LOCK = threading.RLock()


def connect_account(jar, owner=None):
    with CONNECT_LOCK:   # un seul import à la fois : deux requêtes simultanées pour le même compte ne le créent pas deux fois
        return _connect_account(jar, owner)


def _connect_account(jar, owner=None):
    """Enregistre la session. Compte déjà connu (même c_user) : on réutilise son dossier (clés chiffrées, historique) et on remplace seulement les cookies."""
    cu = str(jar.get("c_user") or "")
    if not cu.isdigit():
        raise ValueError("session invalide (identifiant de compte absent)")
    if AUTH.enabled and not owner:
        raise ValueError("utilisateur inconnu")
    name = find_account_name(cu)
    ex = ACCOUNTS.get(name) if name else None
    if AUTH.enabled and ex and ex.owner and ex.owner != owner:
        raise ValueError("ce compte Messenger est déjà relié à un autre utilisateur de ce hub")
    check_session(jar)   # refuse une session que Messenger n'accepte pas, AVANT de toucher aux cookies existants
    reused = bool(name)
    name = name or new_account_name(cu)
    d = account_dir(name)
    tmp = d / "cookies.json.new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(jar, f, indent=2)
    os.replace(tmp, d / "cookies.json")
    old = ACCOUNTS.pop(name, None)
    if old:   # déjà actif : on le redémarre avec la nouvelle session (un seul client par compte)
        for k in [k for k in timers if acct_of(k) == name]:
            cancel_timer(k)
        old.shutdown()
    add_account(name, d, owner)
    return name, reused


# ---------------------------------------------------------------- connexion depuis le navigateur du client (extension « Relais Connect »)
EXT_CODES = {}     # empreinte du code -> {"owner", "exp"}
EXT_FAILS = {}     # adresse -> [horodatages d'échecs]
EXT_DIR = HERE.parent / "extension"


def ext_new_code(owner):
    now = time.time()
    with L:
        for h in [h for h, v in EXT_CODES.items() if v["exp"] < now]:
            del EXT_CODES[h]
        if sum(1 for v in EXT_CODES.values() if v["owner"] == owner) >= 5:
            raise ValueError("trop de connexions en attente : réessaie dans quelques minutes")
        code = secrets.token_urlsafe(24)
        EXT_CODES[hashlib.sha256(code.encode()).hexdigest()] = {"owner": owner, "exp": now + 600}
    return code


def ext_import(code, cookies, ip):
    """Appelé par l'extension (sans session du hub) : le code à usage unique, émis pour un utilisateur connecté, prouve à qui rattacher le compte."""
    now = time.time()
    with L:
        fl = [t for t in EXT_FAILS.get(ip, []) if now - t < 600]
        EXT_FAILS[ip] = fl
        if len(fl) >= 10:
            return {"error": "trop d'essais : réessaie dans quelques minutes"}
    h = hashlib.sha256(str(code or "")[:200].encode()).hexdigest()
    with L:
        ent = EXT_CODES.pop(h, None)   # pris de façon atomique : deux requêtes simultanées ne peuvent pas l'utiliser toutes les deux
    if not ent or ent["exp"] < now:
        with L:
            EXT_FAILS.setdefault(ip, []).append(now)
        time.sleep(0.5)
        return {"error": "code expiré : relance la connexion depuis le hub"}
    jar = parse_curl_cookies(str(cookies or "")[:8000])
    try:
        if not jar:
            raise ValueError("session Messenger introuvable dans ce navigateur")
        name, reused = connect_account(jar, ent["owner"])
    except ValueError as ex:
        with L:
            EXT_CODES[h] = ent   # échec (session refusée, etc.) : le code reste valable pour une nouvelle tentative
        return {"error": str(ex)}
    return {"ok": True, "name": name, "reused": reused}


def ext_zip(origin):
