"""Synchronisation de l'historique, noms des contacts, surveillance et synchro de secours."""

import threading
import time

from .accounts import ACCOUNTS
from .context import log
from .db import NOW, q, setting, x
from .tasks import tp


fetch_waiters = {}   # (compte, thread) -> {"ev": Event, "count": n}


def import_history(key, pages=3, report=True):
    rows = q("SELECT * FROM chats WHERE key=?", (key,))
    if not rows or not ACCOUNTS.get(rows[0]["account"]):
        return 0
    chat, acct = rows[0], ACCOUNTS[rows[0]["account"]]
    if chat["route"] == "e2ee" or chat["kind"] in (15, 16):
        if acct.state.get("history") != "enrolled":
            log("warn", "Conversation chiffrée : restaure d'abord l'historique chiffré avec ton code PIN (bouton 🔒 en haut)", key)
            return 0
        return import_history_e2ee(key, chat, acct, pages, report)
    wkey = (acct.name, chat["thread"])
    wkey = (acct.name, chat["thread"])
    before = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"]
    if report:
        tp(0, pages, "messages plus anciens")
    for _pg in range(pages):
        if report:
            tp(_pg, detail=f"page {_pg + 1} sur {pages}")
        old = q("SELECT ts,id FROM messages WHERE chat_key=? AND id LIKE 'mid.%' ORDER BY ts ASC LIMIT 1", (key,))
        cmd = {"op": "fetch", "thread": chat["thread"]}
        if old:
            cmd.update(ref_ts=old[0]["ts"], ref_id=old[0]["id"])
        w = {"ev": threading.Event(), "count": 0, "err": None}
        fetch_waiters[wkey] = w
        n0 = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"]
        if not acct.send(cmd) or not w["ev"].wait(40):
            break
        # les anciens messages arrivent de façon asynchrone après l'accusé : on attend qu'ils se stabilisent
        last, stable_since, t0 = n0, time.time(), time.time()
        while time.time() - t0 < 12:
            time.sleep(0.5)
            cur = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"]
            if cur != last:
                last, stable_since = cur, time.time()
            elif time.time() - stable_since > (2.5 if last > n0 else 5):
                break
        if w["err"] or last == n0:
            break
        time.sleep(1.5)  # on reste doux avec Meta
    fetch_waiters.pop(wkey, None)
    added = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"] - before
    if added == 0 and before == 0 and acct.state.get("history") == "enrolled":
        # rien dans la boîte classique : le fil est peut-être chiffré, on essaie l'archive chiffrée
        added = import_history_e2ee(key, chat, acct, pages, report)
    log("info", f"Historique importé : {added} message(s) de plus", key)
    return added


SYNC_LOCK = threading.Lock()


SYNC_LAST = {}   # chat_key -> dernier passage (ms)


SYNC_INFO = {"last_run": 0, "last_new": 0}


def _count(key):
    return q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"]


def sync_chat(key):
    """Rattrape les messages récents d'une conversation (filet de sécurité du temps réel). Retourne le nombre de nouveaux messages."""
    rows = q("SELECT * FROM chats WHERE key=?", (key,))
    if not rows or not ACCOUNTS.get(rows[0]["account"]):
        return 0
    chat, acct = rows[0], ACCOUNTS[rows[0]["account"]]
    SYNC_LAST[key] = NOW()
    before = _count(key)
    if chat["route"] == "e2ee" or chat["kind"] in (15, 16):
        if acct.state.get("history") != "enrolled" or not acct.state.get("e2ee"):
            return 0  # chiffré : on dépend du direct (et de l'archive si le PIN a été restauré)
        w = {"ev": threading.Event(), "count": 0, "err": None, "next": 0, "has_more": False}
        fetch_waiters[(acct.name, "h" + str(chat["thread"]))] = w
        if acct.send({"op": "history_fetch", "chat": str(chat["thread"]), "before": 0, "count": 30}):
            w["ev"].wait(60)
        fetch_waiters.pop((acct.name, "h" + str(chat["thread"])), None)
    else:
        if not acct.state.get("classic"):
            return 0
        w = {"ev": threading.Event(), "count": 0, "err": None}
        fetch_waiters[(acct.name, chat["thread"])] = w
        if acct.send({"op": "fetch", "thread": chat["thread"]}):  # sans référence = ouverture du fil : renvoie les messages récents
            w["ev"].wait(40)
        fetch_waiters.pop((acct.name, chat["thread"]), None)
        last, since, t0 = before, time.time(), time.time()   # les messages arrivent juste après l'accusé
        while time.time() - t0 < 10:
            time.sleep(0.5)
            cur = _count(key)
            if cur != last:
                last, since = cur, time.time()
            elif time.time() - since > 2.5:
                break
    return _count(key) - before


def sync_many(keys):
    total = 0
    tp(0, len(keys))
    with SYNC_LOCK:
        for i, k in enumerate(keys):
            nm = (q("SELECT name FROM chats WHERE key=?", (k,)) or [{"name": ""}])[0]["name"]
            tp(i, detail=nm or k.split(":")[-1])
            try:
                total += max(0, sync_chat(k))
            except Exception as ex:
                log("error", f"Synchronisation : {ex}", k)
            time.sleep(1.2)
            tp(i + 1)
    SYNC_INFO.update(last_run=NOW(), last_new=total)
    return total


def watchdog():
    """Relance le fil de lecture s'il est mort, et le client s'il reste déconnecté trop longtemps."""
    for a in ACCOUNTS.values():
        if a.stop or a.state.get("expired"):   # session refusée : on attend que l'utilisateur reconnecte le compte
            continue
        if a.thread is not None and not a.thread.is_alive():
            log("warn", f"[{a.name}] fil de lecture arrêté : relance")
            if a.proc and a.proc.poll() is None:
                a.proc.terminate()
            a.start()
            continue
        if a.state.get("running") and not a.state.get("classic") and not a.state.get("e2ee"):
            a.down_since = a.down_since or NOW()
            if NOW() - a.down_since > 180_000:
                log("warn", f"[{a.name}] déconnecté depuis plus de 3 min : redémarrage du client")
                a.down_since = 0
                if a.proc and a.proc.poll() is None:
                    a.proc.terminate()
        else:
            a.down_since = 0


def autosync_loop():
    """Filet de sécurité : relit à tour de rôle les conversations actives (une requête toutes les ~6 s au plus)."""
    while True:
        time.sleep(6)
        try:
            watchdog()
        except Exception as ex:
            log("error", f"Surveillance : {ex}")
        try:
            horizon = NOW() - 7 * 86_400_000
            due = q("SELECT key, account FROM chats WHERE enabled=1 AND is_group=0 AND last_ts>? ORDER BY key", (horizon,))
            due = [r["key"] for r in due
                   if int(setting("sync_s", r["account"]) or 0) > 0
                   and NOW() - SYNC_LAST.get(r["key"], 0) > int(setting("sync_s", r["account"])) * 1000]
            if not due or SYNC_LOCK.locked():
                continue
            key = min(due, key=lambda k: SYNC_LAST.get(k, 0))
            with SYNC_LOCK:
                new = sync_chat(key)
            if new > 0:
                log("info", f"Synchronisation de secours : {new} message(s) rattrapé(s)", key)
        except Exception as ex:
            log("error", f"Synchronisation automatique : {ex}")


def import_history_e2ee(key, chat, acct, pages, report=True):
    user = str(chat["thread"])
    wkey = (acct.name, "h" + user)
    before = (q("SELECT MIN(ts) t FROM messages WHERE chat_key=?", (key,))[0]["t"] or 0)
    total0 = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"]
    if report:
        tp(0, pages, "historique chiffré")
    for _pg in range(pages):
        if report:
            tp(_pg, detail=f"page {_pg + 1} sur {pages}")
        w = {"ev": threading.Event(), "count": 0, "err": None, "next": 0, "has_more": False}
        fetch_waiters[wkey] = w
        if not acct.send({"op": "history_fetch", "chat": user, "before": before, "count": 30}) or not w["ev"].wait(90):
            break
        if w["err"]:
            log("warn", f"Historique chiffré : {w['err']}", key)
            break
        if not w["has_more"] or not w["next"] or (before and w["next"] >= before):
            break
        before = w["next"]
        time.sleep(1.5)
    fetch_waiters.pop(wkey, None)
    added = q("SELECT COUNT(*) c FROM messages WHERE chat_key=?", (key,))[0]["c"] - total0
    log("info", f"Historique chiffré importé : {added} message(s) de plus", key)
    return added


def resolve_names(only=None):
    """Retrouve nom + photo des conversations qui n'en ont pas, compte par compte."""
    for a in list(ACCOUNTS.values()):
        if (only is None or a.name in only) and a.state.get("classic"):
            _resolve_names_for(a)


def _resolve_names_for(acct):
    rows = q("SELECT key,thread FROM chats WHERE account=? AND is_group=0 AND (name='' OR name IS NULL) AND lookup_ts<? "
             "ORDER BY last_ts DESC LIMIT 300", (acct.name, NOW() - 86_400_000))
    if not rows:
        return
    found = 0
    tp(0, len(rows), "profils des conversations")
    for i, r in enumerate(rows):
        tp(i)
        w = {"ev": threading.Event(), "found": False}
        fetch_waiters[(acct.name, "c" + str(r["thread"]))] = w
        if not acct.send({"op": "contact", "thread": r["thread"]}):
            break
        w["ev"].wait(25)
        fetch_waiters.pop((acct.name, "c" + str(r["thread"])), None)
        x("UPDATE chats SET lookup_ts=? WHERE key=?", (NOW(), r["key"]))
        found += 1 if w["found"] else 0
        time.sleep(0.8)  # on reste doux avec Meta
    # 2e passe : fils sans message connu -> on les ouvre, on lit l'expéditeur, puis on cherche son profil
    still = q("SELECT key,thread FROM chats WHERE account=? AND is_group=0 AND (name='' OR name IS NULL) AND "
              "(SELECT COUNT(*) FROM messages WHERE chat_key=chats.key)=0 ORDER BY last_ts DESC LIMIT 60", (acct.name,))
    via_sender = 0
    tp(len(rows), len(rows) + len(still), "conversations sans message")
    for j, r in enumerate(still):
        tp(len(rows) + j)
        w = {"ev": threading.Event(), "count": 0, "err": None}
        fetch_waiters[(acct.name, r["thread"])] = w
        if not acct.send({"op": "fetch", "thread": r["thread"]}):
            break
        w["ev"].wait(30)
        fetch_waiters.pop((acct.name, r["thread"]), None)
        time.sleep(4)  # les messages arrivent juste après l'accusé
        senders = {}
        for m in q("SELECT sender FROM messages WHERE chat_key=? AND src='contact'", (r["key"],)):
            if str(m["sender"]).isdigit() and int(m["sender"]) > 0:
                senders[int(m["sender"])] = senders.get(int(m["sender"]), 0) + 1
        if not senders:
            continue
        sid = max(senders, key=senders.get)
        if sid != r["thread"]:
            c = q("SELECT name,pic FROM contacts WHERE account=? AND id=? AND name<>''", (acct.name, sid))
            if not c:
                w2 = {"ev": threading.Event(), "found": False}
                fetch_waiters[(acct.name, "c" + str(sid))] = w2
                if acct.send({"op": "contact", "thread": sid}):
                    w2["ev"].wait(25)
                fetch_waiters.pop((acct.name, "c" + str(sid)), None)
                time.sleep(1)
                c = q("SELECT name,pic FROM contacts WHERE account=? AND id=? AND name<>''", (acct.name, sid))
            if c:
                x("UPDATE chats SET name=?, pic=CASE WHEN ?<>'' THEN ? ELSE pic END WHERE key=?",
                  (c[0]["name"], c[0]["pic"] or "", c[0]["pic"] or "", r["key"]))
                via_sender += 1
        time.sleep(0.8)
    log("info", f"Noms et photos recherchés pour {len(rows)} conversation(s) : {found} profil(s) trouvé(s), {via_sender} via l'expéditeur")
