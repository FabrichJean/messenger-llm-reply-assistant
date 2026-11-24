"""Événements entrants du client Messenger : messages, modifications, suppressions."""

import json
import random
import re
import sqlite3
import threading
import time

from .accounts import save_accounts
from .attachments import ATT_LABEL, ATT_PLACEHOLDER, drop_attachments, media_waiters, store_attachment
from .config import DATA, HUB_DEBUG
from .context import log
from .db import NOW, is_paused, q, setting, x
from .llm.outbox import llm_sent, owner_last
from .llm.replies import schedule_reply
from .llm.style import maybe_auto_style
from .llm.timers import cancel_timer
from .sync import fetch_waiters, resolve_names
from .tasks import run_bg


ONE_TO_ONE_KINDS = {1, 7, 10, 13, 15}   # ONE_TO_ONE, TINCAN, CARRIER, TINCAN_DISAPPEARING, ENCRYPTED_OVER_WA_ONE_TO_ONE


threads_loaded = set()


def ensure_chat(acct, key, thread, name=None):
    if not q("SELECT 1 FROM chats WHERE key=?", (key,)):
        nm, pic = name, ""
        r = q("SELECT name,pic FROM contacts WHERE account=? AND id=?", (acct.name, thread))
        if r:
            nm = nm or r[0]["name"]
            pic = r[0]["pic"] or ""
        x("INSERT INTO chats(key,account,name,thread,pic) VALUES(?,?,?,?,?)", (key, acct.name, nm or "", thread, pic))


def handle_event(acct, e):
    t = e.get("type")
    now_ms = NOW()
    acct.state["last_event"] = now_ms
    if t == "message" and not e.get("history"):
        acct.state["last_message"] = now_ms
        acct.state["last_message_route"] = "chiffré" if e.get("e2ee") else "classique"
    if t == "status":
        s = e.get("state")
        if s in ("connected", "reconnected", "disconnected", "e2ee_connected", "e2ee_disconnected"):
            log("info", f"[{acct.name}] canal {'chiffré' if s.startswith('e2ee') else 'classique'} : {s.replace('e2ee_', '')}")
        if s == "connected" or s == "reconnected":
            acct.state["classic"] = True
            if acct.name not in threads_loaded:
                threads_loaded.add(acct.name)
                threading.Timer(5, lambda: acct.send({"op": "threads"})).start()
        elif s == "disconnected":
            acct.state["classic"] = False
        elif s == "e2ee_connected":
            acct.state["e2ee"] = True
            acct.send({"op": "history_status"})
        elif s == "e2ee_disconnected":
            acct.state["e2ee"] = False
        elif s == "e2ee_unhandled":
            log("warn", f"[{acct.name}] message chiffré d'un type non géré : {str(e.get('detail'))[:80]}")
        elif s == "e2ee_not_registered":
            acct.state["note"] = "canal chiffré non enregistré"
        elif s == "fatal":
            log("error", f"[{acct.name}] erreur fatale du client: {e.get('error')}")
    elif t == "self":
        label = re.sub(r"[\x00-\x1f\x7f]", "", str(e.get("name") or "")).strip()[:60]
        if label and label != acct.label:
            acct.label = label
            save_accounts()
    elif t == "contact":
        pic = e.get("pic") or ""
        x("INSERT INTO contacts(account,id,name,pic) VALUES(?,?,?,?) ON CONFLICT(account,id) DO UPDATE SET "
          "name=excluded.name, pic=CASE WHEN excluded.pic<>'' THEN excluded.pic ELSE contacts.pic END",
          (acct.name, e["id"], e["name"], pic))
        ckey = f"{acct.name}:{e['id']}"
        ensure_chat(acct, ckey, int(e["id"]), e["name"])  # chaque contact est cherchable, même sans message
        x("UPDATE chats SET name=? WHERE key=?", (e["name"], ckey))
        if pic:
            x("UPDATE chats SET pic=? WHERE key=?", (pic, f"{acct.name}:{e['id']}"))
    elif t == "thread":
        key = f"{acct.name}:{e['id']}"
        if not e.get("id"):
            return
        ensure_chat(acct, key, int(e["id"]), e.get("name"))
        kind = int(e.get("kind") or 0)
        if kind:
            x("UPDATE chats SET kind=? WHERE key=?", (kind, key))
            if kind not in ONE_TO_ONE_KINDS:
                x("UPDATE chats SET is_group=1, enabled=0 WHERE key=?", (key,))
            elif kind == 15:  # 1:1 chiffré : on répond par le canal chiffré
                x("UPDATE chats SET route='e2ee', jid=? WHERE key=? AND (jid='' OR jid IS NULL)", (f"{e['id']}@msgr", key))
        if e.get("name"):
            x("UPDATE chats SET name=? WHERE key=? AND (name='' OR name IS NULL)", (e["name"], key))
        if e.get("pic"):
            x("UPDATE chats SET pic=? WHERE key=?", (e["pic"], key))
        if e.get("ts"):
            x("UPDATE chats SET last_ts=MAX(last_ts,?) WHERE key=?", (int(e["ts"]), key))
    elif t == "edit":
        apply_edit(acct, e)
    elif t == "delete":
        apply_delete(acct, e)
    elif t == "debug" and HUB_DEBUG:
        # noms de champs seulement (jamais de contenu) : sert à comprendre ce que Facebook envoie
        with open(DATA / "events.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "event": e.get("event"), "fields": e.get("fields")}, ensure_ascii=False) + "\n")
    elif t == "message":
        process_message(acct, e)
    elif t == "attachment":
        store_attachment(acct, e)
    elif t == "diag":   # structure reçue pour un message sans pièce jointe reconnue (noms de tables et indicateurs, jamais de contenu)
        log("info", f"[{acct.name}] diagnostic pièce jointe : lignes={json.dumps(e.get('rows'), ensure_ascii=False)}"[:1500])
    elif t == "media_ready":
        w = media_waiters.get((acct.name, str(e.get("req"))))
        if w:
            w.update(file=e.get("file"), size=int(e.get("size") or 0), err=e.get("error"))
            w["ev"].set()
    elif t == "history":
        acct.state["history"] = e.get("state")
        acct.state["history_err"] = e.get("error") or ""
        acct.state["history_attempts"] = e.get("attempts_remaining")
        if e.get("state") == "enrolled":
            log("info", f"[{acct.name}] historique chiffré : accès restauré")
        elif e.get("state") == "error":
            log("warn", f"[{acct.name}] historique chiffré : {e.get('error')}"
                        + (f" ({e.get('attempts_remaining')} essai(s) restant(s))" if e.get("attempts_remaining") is not None else ""))
    elif t == "history_fetched":
        w = fetch_waiters.get((acct.name, "h" + str(e.get("chat"))))
        if w:
            w.update(count=int(e.get("count") or 0), err=e.get("error"), next=int(e.get("next") or 0), has_more=bool(e.get("has_more")))
            w["ev"].set()
    elif t == "threads_done":
        log("info", f"[{acct.name}] liste des conversations complétée ({e.get('pages')} page(s) de plus)")
        run_bg("names", resolve_names)
    elif t == "contact_done":
        w = fetch_waiters.get((acct.name, "c" + str(e.get("id"))))
        if w:
            w["found"] = bool(e.get("found"))
            w["ev"].set()
    elif t == "fetched":
        w = fetch_waiters.get((acct.name, int(e.get("thread") or 0)))
        if w:
            w["count"] = int(e.get("count") or 0)
            if w["count"] == 0:
                log("debug", f"[{acct.name}] import : réponse sans message, champs reçus = {e.get('fields')}")
            w["err"] = e.get("error")
            w["ev"].set()
    elif t == "error":
        log("error", f"[{acct.name}] {e.get('error')}")


def _target_keys(acct, e):
    """Conversation(s) concernée(s) : par jid/fil si connu, sinon on retrouve le message par son identifiant."""
    mid = str(e.get("id") or "")
    if not mid:
        return []
    rows = q("SELECT chat_key FROM messages WHERE id=? AND chat_key LIKE ?", (mid, acct.name + ":%"))
    return [r["chat_key"] for r in rows]


def apply_edit(acct, e):
    text = (e.get("text") or "").strip()
    if not text:
        return
    for key in _target_keys(acct, e):
        cur = x("UPDATE messages SET text=?, edited=1, local_edit=0, orig_text='' WHERE id=? AND chat_key=? AND text<>?", (text, e["id"], key, text))
        if cur.rowcount:
            last = q("SELECT id FROM messages WHERE chat_key=? ORDER BY ts DESC LIMIT 1", (key,))
            if last and last[0]["id"] == e["id"]:
                x("UPDATE chats SET last_text=? WHERE key=?", (text, key))
            log("info", "Message modifié dans Messenger : mis à jour ici", key)


def apply_delete(acct, e):
    for key in _target_keys(acct, e):
        cur = x("UPDATE messages SET deleted=1 WHERE id=? AND chat_key=? AND deleted=0", (e["id"], key))
        drop_attachments(acct, key, e["id"])   # un message retiré : ses pièces jointes aussi (fichiers compris)
        if cur.rowcount:
            cancel_timer(key)  # inutile de répondre à un message retiré
            last = q("SELECT id FROM messages WHERE chat_key=? ORDER BY ts DESC LIMIT 1", (key,))
            if last and last[0]["id"] == e["id"]:
                x("UPDATE chats SET last_text='🚫 message supprimé' WHERE key=?", (key,))
            log("info", "Message supprimé dans Messenger : marqué ici", key)


def process_message(acct, e):
    thread = int(e.get("thread") or 0)
    if not thread:
        return
    key = f"{acct.name}:{thread}"
    text = (e.get("text") or "").strip()
    ts = int(e.get("ts") or NOW())
    from_me = bool(e.get("from_me"))
    history = bool(e.get("history"))
    # écho d'un message que nous venons d'envoyer nous-mêmes
    if from_me:
        for (tx, tts) in llm_sent.get(key, []):
            if tx.strip() == text and abs(NOW() - tts) < 120_000:
                return
    if from_me and text and e.get("id"):
        twin = q("SELECT id FROM messages WHERE chat_key=? AND (id LIKE 'llm-%' OR id LIKE 'owner-%') AND TRIM(text)=? "
                 "AND ABS(ts-?)<900000 LIMIT 1", (key, text, ts))
        if twin:  # c'est l'écho d'un message envoyé par nous (LLM ou toi via l'app) : on garde une seule ligne, avec le vrai identifiant
            try:
                x("UPDATE messages SET id=? WHERE chat_key=? AND id=?", (e["id"], key, twin[0]["id"]))
            except sqlite3.IntegrityError:
                pass
            return
    ensure_chat(acct, key, thread)
    # groupes : e2ee hors serveur msgr, ou classique avec un expéditeur différent du fil
    jid = e.get("chat") or ""
    sender = int(e.get("sender") or 0)
    is_group = (bool(jid) and not jid.endswith("@msgr")) or (not e.get("e2ee") and not from_me and sender and sender != thread)
    if is_group:
        x("UPDATE chats SET is_group=1, enabled=0 WHERE key=?", (key,))
    shown = text or ATT_PLACEHOLDER
    if not text and e.get("id"):   # la pièce jointe peut être arrivée avant le message : on utilise son étiquette
        ar = q("SELECT kind FROM attachments WHERE chat_key=? AND msg_id=? ORDER BY idx LIMIT 1", (key, e["id"]))
        if ar:
            shown = ATT_LABEL.get(ar[0]["kind"], ATT_PLACEHOLDER)
    cur = x("INSERT OR IGNORE INTO messages(id,chat_key,ts,sender,text,src) VALUES(?,?,?,?,?,?)",
            (e.get("id") or f"x{ts}{random.random()}", key, ts, str(sender), shown, "owner" if from_me else "contact"))
    if cur.rowcount == 0:
        return  # doublon
    if not text and e.get("id") and not history:   # message sans texte : sa pièce jointe devrait arriver aussitôt ; sinon on le dit (type non reconnu)
        def _check_att(k=key, mid=e["id"]):
            if not q("SELECT 1 FROM attachments WHERE chat_key=? AND msg_id=? LIMIT 1", (k, mid)):
                log("warn", "Message sans texte et sans pièce jointe reconnue (type non géré ?)", k)
        threading.Timer(4, _check_att).start()
    x("UPDATE chats SET last_ts=MAX(last_ts,?), last_text=CASE WHEN ?>=last_ts THEN ? ELSE last_text END WHERE key=?",
      (ts, ts, shown, key))
    if from_me:
        owner_last[key] = max(owner_last.get(key, 0), ts)
        cancel_timer(key)  # le propriétaire a repris la main
        maybe_auto_style(acct.name)
        return
    late_ok = False
    if history and text:
        c0 = q("SELECT * FROM chats WHERE key=?", (key,))[0]
        max_age = int(setting("late_reply_min", acct.name) or 0) * 60_000
        if (c0["enabled"] and not c0["is_group"] and ts >= c0["enabled_at"] and max_age > 0 and NOW() - ts <= max_age
                and not q("SELECT 1 FROM messages WHERE chat_key=? AND ts>? AND src IN ('owner','llm') LIMIT 1", (key, ts))):
            late_ok = True  # arrivé en retard (reconnexion, resynchronisation) mais récent et sans réponse
            log("info", "Message arrivé en retard, récent et sans réponse : traité comme un message en direct", key)
    if history and not late_ok:
        pass
    if not history or late_ok:
        log("info", f"Message entrant ({'chiffré' if e.get('e2ee') else 'classique'}){' [vide]' if not text else ''}", key)
        if e.get("e2ee"):
            x("UPDATE chats SET route='e2ee', jid=? WHERE key=?", (jid, key))
        else:
            x("UPDATE chats SET route='classic' WHERE key=? AND (jid='' OR jid IS NULL)", (key,))
    if history and not late_ok:
        return
    chat = q("SELECT * FROM chats WHERE key=?", (key,))[0]
    if not chat["enabled"]:
        return
    if not text:
        log("info", "Message sans texte (pièce jointe / sticker) : ignoré", key)
    elif chat["is_group"]:
        log("info", "Groupe : le LLM ne répond pas", key)
    elif ts < chat["enabled_at"]:
        log("info", "Message antérieur à l'activation : ignoré", key)
    elif is_paused(acct.name):
        log("info", "Pause active : pas de réponse", key)
    else:
        log("info", f"Message reçu ({chat['mode']}) : réponse dans {chat['delay_s']} s", key)
        schedule_reply(key, chat["delay_s"])


def dedupe_owner_echoes():
    """Supprime les anciennes lignes « toi » qui sont en fait des échos de réponses du LLM (elles faussaient le silence et le style)."""
    cur = x("DELETE FROM messages WHERE src='owner' AND id NOT LIKE 'owner-%' AND EXISTS (SELECT 1 FROM messages l "
            "WHERE l.chat_key=messages.chat_key AND l.src='llm' AND TRIM(l.text)=TRIM(messages.text) AND ABS(l.ts-messages.ts)<900000)")
    if cur.rowcount:
        log("info", f"Nettoyage : {cur.rowcount} écho(s) de réponses du LLM retirés de ton historique")
    for r in q("SELECT chat_key, MAX(ts) t FROM messages WHERE src='owner' GROUP BY chat_key"):
        owner_last[r["chat_key"]] = r["t"]  # la reprise en main survit au redémarrage
