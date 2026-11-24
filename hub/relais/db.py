"""Base de données SQLite (verrou global, schéma, requêtes) et réglages."""

import sqlite3
import threading
import time

from .config import DATA
from .context import AUTH


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


NOW = lambda: int(time.time() * 1000)


def _in(names):
    """(« ?,?,? », valeurs) pour un filtre SQL « IN » ; « '' » quand la liste est vide."""
    names = tuple(sorted(names))
    return (",".join("?" * len(names)) or "''"), names
