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
