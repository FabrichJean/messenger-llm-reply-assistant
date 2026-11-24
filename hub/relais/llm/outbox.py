"""Envoi des messages, minuteries de réponse et compteurs d'envois."""

import random

from ..accounts import ACCOUNTS
from ..context import log
from ..db import NOW, q, x


owner_last = {}      # chat_key -> ts ms du dernier message écrit par le propriétaire (reprise en main)


llm_sent = {}        # chat_key -> [(texte, ts)] pour ignorer l'écho de nos propres envois


def owner_recent_ts(key, chat):
    """Dernier message « de toi » qui compte pour le silence (0 si l'option « ne jamais se taire » est active ou si le silence a été levé)."""
    if chat.get("takeover_off"):
        return 0
    ts = owner_last.get(key, 0)
    return ts if ts > (chat.get("unmute_ts") or 0) else 0


def llm_count_last_hour(key=None, account=None):
    """Réponses AUTOMATIQUES de la dernière heure (les réponses forcées avec ⚡ ou validées à la main ne comptent pas)."""
    since = NOW() - 3_600_000
    if key:
        return q("SELECT COUNT(*) c FROM messages WHERE chat_key=? AND src='llm' AND auto=1 AND ts>?", (key, since))[0]["c"]
    if account:
        return q("SELECT COUNT(*) c FROM messages m JOIN chats c ON c.key=m.chat_key WHERE m.src='llm' AND m.auto=1 AND m.ts>? AND c.account=?", (since, account))[0]["c"]
    return q("SELECT COUNT(*) c FROM messages WHERE src='llm' AND auto=1 AND ts>?", (since,))[0]["c"]


def send_text(key, text, src, auto=False):
    chat = q("SELECT * FROM chats WHERE key=?", (key,))[0]
    acct = ACCOUNTS.get(chat["account"])
    if not acct:
        return False
    if chat["route"] == "e2ee" and chat["jid"]:
        cmd = {"chat": chat["jid"], "text": text}
    else:
        cmd = {"thread": chat["thread"], "text": text}
    if not acct.send(cmd):
        log("error", "Envoi impossible : client arrêté", key)
        return False
    ts = NOW()
    llm_sent.setdefault(key, []).append((text, ts))
    llm_sent[key] = llm_sent[key][-10:]
    x("INSERT INTO messages(id,chat_key,ts,sender,text,src,auto) VALUES(?,?,?,?,?,?,?)",
      (f"{src}-{ts}-{random.randint(0, 99999)}", key, ts, "me", text, src, 1 if auto else 0))
    x("UPDATE chats SET last_ts=MAX(last_ts,?), last_text=?, attention=0, attention_note='' WHERE key=?", (ts, text, key))
    if src == "owner":
        owner_last[key] = ts
    log("info", ("Réponse du LLM envoyée" if src == "llm" else "Message envoyé") + f" ({len(text)} car.)", key)
    return True
