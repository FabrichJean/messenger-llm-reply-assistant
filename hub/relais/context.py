"""Contexte de la requête en cours (utilisateur connecté), journal en mémoire, droits."""

import os
import re
import threading
import time
from collections import deque

from . import auth as authmod
from .config import DATA


AUTH = authmod.Auth(DATA, os.environ.get("HUB_PASSWORD", ""), os.environ.get("HUB_ADMIN_USER", "admin"))


def acct_of(key):
    """Compte d'une conversation (clé « compte:identifiant »)."""
    return str(key).split(":", 1)[0]


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
