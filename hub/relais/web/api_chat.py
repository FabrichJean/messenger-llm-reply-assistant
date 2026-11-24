"""Routes des conversations : réglages, envoi, brouillons, aperçu, préparation, épinglage, suppression."""

import threading
from ..accounts import ACCOUNTS, default_account
from ..attachments import media_dir
from ..context import cur_name, log
from ..db import NOW, q, x
from ..events import ensure_chat
from ..llm import memory as mem_mod
from ..llm.memory_update import update_memory
from ..llm.outbox import send_text
from ..llm.prepare import PREPARED, force_reply, prepare_chat, preview_reply
from ..llm.timers import cancel_timer
from ..sync import import_history, sync_many
from ..tasks import run_bg, task, tp


def chat_settings(b):
    # POST /api/chat/settings
    key = b["key"]
    rows = q("SELECT * FROM chats WHERE key=?", (key,))
    if not rows:
        return {"error": "conversation inconnue"}
    if "enabled" in b:
        if b["enabled"] and rows[0]["is_group"]:
            return {"error": "le LLM n'est pas activable dans un groupe"}
        if b["enabled"] and not rows[0]["enabled"]:
            x("UPDATE chats SET enabled=1, enabled_at=? WHERE key=?", (NOW(), key))
            log("info", "LLM activé pour cette conversation (messages à partir de maintenant)", key)
            run_bg("import", import_history, key, 6)
        elif not b["enabled"]:
            x("UPDATE chats SET enabled=0 WHERE key=?", (key,))
            cancel_timer(key)
            log("info", "LLM désactivé pour cette conversation", key)
    if b.get("mode") in ("auto", "draft"):
        x("UPDATE chats SET mode=? WHERE key=?", (b["mode"], key))
    if "memory" in b:
        x("UPDATE chats SET memory=?, memory_ts=? WHERE key=?", (str(b["memory"])[:mem_mod.MAX_CHARS], NOW(), key))
    if "instructions" in b:
        x("UPDATE chats SET instructions=? WHERE key=?", (str(b["instructions"])[:4000], key))
    if "max_per_hour" in b:
        x("UPDATE chats SET max_per_hour=? WHERE key=?", (max(1, min(int(b["max_per_hour"]), 100)), key))
    if "trusted" in b:
        x("UPDATE chats SET trusted=? WHERE key=?", (1 if b["trusted"] else 0, key))
        log("info", "Contact de confiance : " + ("ACTIVÉ (pas de blocage sur les messages suspects)" if b["trusted"] else "désactivé"), key)
    if "takeover_off" in b:
        x("UPDATE chats SET takeover_off=? WHERE key=?", (1 if b["takeover_off"] else 0, key))
    if "delay_s" in b:
        x("UPDATE chats SET delay_s=? WHERE key=?", (max(0, min(int(b["delay_s"]), 300)), key))
    return {"ok": True}


def draft(b):
    # POST /api/draft
    d = q("SELECT * FROM drafts WHERE id=? AND status='pending'", (b["id"],))
    if not d:
        return {"error": "brouillon introuvable"}
    if b.get("action") == "send":
        text = str(b.get("text") or d[0]["text"]).strip()
        if text and send_text(d[0]["chat_key"], text, "llm"):
            x("UPDATE drafts SET status='sent' WHERE id=?", (b["id"],))
            return {"ok": True}
        return {"error": "envoi impossible"}
    x("UPDATE drafts SET status='discarded' WHERE id=?", (b["id"],))
    return {"ok": True}


def send(b):
    # POST /api/send
    text = str(b.get("text") or "").strip()
    if not text or not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "message vide ou conversation inconnue"}
    return {"ok": send_text(b["key"], text, "owner")}


def chat_import(b):
    # POST /api/chat/import
    if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "conversation inconnue"}
    return {"ok": run_bg("import", import_history, b["key"], max(1, min(int(b.get("pages", 10)), 30)))}


def chat_add(b):
    # POST /api/chat/add
    acct = ACCOUNTS.get(b.get("account") or default_account())
    try:
        fid = int(str(b.get("id")).strip())
    except ValueError:
        return {"error": "identifiant invalide (nombre)"}
    if not acct or fid <= 0:
        return {"error": "compte ou identifiant invalide"}
    key = f"{acct.name}:{fid}"
    ensure_chat(acct, key, fid, (b.get("name") or "").strip()[:80])
    if b.get("e2ee"):
        x("UPDATE chats SET route='e2ee', jid=? WHERE key=?", (f"{fid}@msgr", key))
    log("info", "Conversation ajoutée à la main", key)
    return {"ok": True, "key": key}


def chat_prepare(b):
    # POST /api/chat/prepare
    if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "conversation inconnue"}
    if PREPARED.get(b["key"], {}).get("busy"):
        return {"ok": True}
    def _prep(k=b["key"], ow=cur_name()):
        with task("Préparation de la conversation", key="prepare", owner=ow):
            tp(detail="le LLM lit l'historique")
            prepare_chat(k)
    threading.Thread(target=_prep, daemon=True).start()
    return {"ok": True}


def chat_prepare_discard(b):
    # POST /api/chat/prepare/discard
    PREPARED.pop(b["key"], None)
    return {"ok": True}


def message_edit(b):
    # POST /api/message/edit
    key, mid = b.get("key"), b.get("id")
    rows = q("SELECT text,local_edit,orig_text FROM messages WHERE chat_key=? AND id=?", (key, mid))
    if not rows:
        return {"error": "message introuvable"}
    cur = rows[0]
    if b.get("revert"):
        if not cur["local_edit"]:
            return {"ok": True}
        new_text, orig, flag = cur["orig_text"], "", 0
    else:
        new_text = str(b.get("text") or "").strip()[:4000]
        if not new_text:
            return {"error": "le texte ne peut pas être vide"}
        orig = cur["orig_text"] if cur["local_edit"] else cur["text"]
        flag = 1 if new_text != orig else 0
        if not flag:
            orig = ""
    x("UPDATE messages SET text=?, local_edit=?, orig_text=? WHERE chat_key=? AND id=?", (new_text, flag, orig, key, mid))
    last = q("SELECT id FROM messages WHERE chat_key=? ORDER BY ts DESC LIMIT 1", (key,))
    if last and last[0]["id"] == mid:
        x("UPDATE chats SET last_text=? WHERE key=?", (new_text, key))
    log("info", "Message modifié dans l'historique local (rien envoyé à Messenger)", key)
    return {"ok": True}


def chat_memory_refresh(b):
    # POST /api/chat/memory/refresh
    def _mem(k=b["key"]):
        with task("Mise à jour de la mémoire de la conversation", key="memory"):
            tp(detail="le LLM relit la conversation")
            try:
                update_memory(k, force=True)
            except Exception as ex:
                log("error", f"Mémoire : {ex}", k)
    threading.Thread(target=_mem, daemon=True).start()
    return {"ok": True}


def chat_sync(b):
    # POST /api/chat/sync
    if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "conversation inconnue"}
    with task("Synchronisation de la conversation", key="sync1"):
        n = sync_many([b["key"]])
    log("info", f"Synchronisation manuelle : {n} message(s) de plus", b["key"])
    return {"ok": True, "new": n}


def chat_raise_limit(b):
    # POST /api/chat/raise_limit
    r = q("SELECT max_per_hour FROM chats WHERE key=?", (b["key"],))
    if not r:
        return {"error": "conversation inconnue"}
    new = min(100, r[0]["max_per_hour"] + 10)
    x("UPDATE chats SET max_per_hour=?, attention=0, attention_note='' WHERE key=?", (new, b["key"]))
    log("info", f"Limite horaire relevée à {new} réponses/h", b["key"])
    return {"ok": True, "max": new}


def chat_unmute(b):
    # POST /api/chat/unmute
    if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "conversation inconnue"}
    x("UPDATE chats SET unmute_ts=? WHERE key=?", (NOW(), b["key"]))
    log("info", "Silence ignoré : le LLM peut de nouveau répondre ici", b["key"])
    return {"ok": True}


def chat_preview(b):
    # POST /api/chat/preview
    with task("Aperçu de la réponse", key="preview"):
        tp(detail="le LLM rédige (rien n'est envoyé)")
        return preview_reply(b["key"])


def chat_send_preview(b):
    # POST /api/chat/send_preview
    text = str(b.get("text") or "").strip()[:1500]
    if not text or not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "texte vide ou conversation inconnue"}
    cancel_timer(b["key"])
    ok = send_text(b["key"], text, "llm")
    return {"ok": ok} if ok else {"error": "envoi impossible (client arrêté ?)"}


def chat_force(b):
    # POST /api/chat/force
    with task("Réponse du LLM" if b.get("send", True) else "Brouillon du LLM", key="force"):
        tp(detail="lecture du contexte, rédaction, contrôles de sécurité")
        return force_reply(b["key"], bool(b.get("send", True)), str(b.get("hint") or ""))


def chat_pin(b):
    # POST /api/chat/pin
    if not q("SELECT 1 FROM chats WHERE key=?", (b.get("key"),)):
        return {"error": "conversation inconnue"}
    x("UPDATE chats SET pinned=? WHERE key=?", (1 if b.get("pinned") else 0, b["key"]))
    return {"ok": True}


def chat_delete(b):
    # POST /api/chat/delete
    key = b.get("key")
    rows = q("SELECT account FROM chats WHERE key=?", (key,))
    if not rows:
        return {"error": "conversation inconnue"}
    if not b.get("confirm"):
        return {"error": "confirmation requise"}
    cancel_timer(key)
    d = media_dir(rows[0]["account"])
    for r in q("SELECT id FROM attachments WHERE chat_key=?", (key,)):
        for suffix in ("", "_p"):
            if d:
                try:
                    (d / (r["id"] + suffix)).unlink()
                except OSError:
                    pass
    for tbl in ("attachments", "messages", "drafts"):
        x(f"DELETE FROM {tbl} WHERE chat_key=?", (key,))
    x("DELETE FROM chats WHERE key=?", (key,))
    log("info", "Conversation supprimée de ce hub (Messenger n'est pas touché)", key)
    return {"ok": True}


def chat_rename(b):
    # POST /api/chat/rename
    name = str(b.get("name") or "").strip()[:80]
    if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
        return {"error": "conversation inconnue"}
    x("UPDATE chats SET name=? WHERE key=?", (name, b["key"]))
    return {"ok": True}


def clear_attention(b):
    # POST /api/clear_attention
    x("UPDATE chats SET attention=0, attention_note='' WHERE key=?", (b["key"],))
    return {"ok": True}


ROUTES = {
    "/api/chat/settings": chat_settings,
    "/api/draft": draft,
    "/api/send": send,
    "/api/chat/import": chat_import,
    "/api/chat/add": chat_add,
    "/api/chat/prepare": chat_prepare,
    "/api/chat/prepare/discard": chat_prepare_discard,
    "/api/message/edit": message_edit,
    "/api/chat/memory/refresh": chat_memory_refresh,
    "/api/chat/sync": chat_sync,
    "/api/chat/raise_limit": chat_raise_limit,
    "/api/chat/unmute": chat_unmute,
    "/api/chat/preview": chat_preview,
    "/api/chat/send_preview": chat_send_preview,
    "/api/chat/force": chat_force,
    "/api/chat/pin": chat_pin,
    "/api/chat/delete": chat_delete,
    "/api/chat/rename": chat_rename,
    "/api/clear_attention": clear_attention,
}
