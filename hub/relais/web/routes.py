"""Routes d'écriture de l'API (POST) et contrôle d'accès central."""

import threading

from ..llm import memory as mem_mod
from ..accounts import ACCOUNTS, connect_account, default_account, has_registered_device, mine, own_chat, parse_curl_cookies, save_accounts
from ..attachments import media_dir
from ..context import AUTH, acct_of, cur_name, is_admin, log
from ..db import NOW, _in, q, set_setting, x
from ..events import ensure_chat
from ..llm.memory_update import update_memory
from ..llm.outbox import send_text
from ..llm.prepare import PREPARED, force_reply, prepare_chat, preview_reply
from ..llm.style import analyze_style, learn_all
from ..llm.timers import cancel_timer, timers
from ..login import LOGIN, _lkey, ext_new_code, login_input, start_login
from ..sync import import_history, resolve_names, sync_many
from ..tasks import run_bg, task, tp
from .users_api import users_api


def _post(path, b):
    if path == "/api/settings":
        scope = b.get("account") or None
        if scope and scope not in ACCOUNTS:
            return {"error": "compte inconnu"}
        for k in ("paused", "model", "owner", "persona", "max_per_hour_global", "takeover_min",
                  "style_profile", "style_cross", "style_auto", "late_reply_min", "sync_s", "judge", "security_level", "classifier", "attack_mode", "link_preview", "link_preview_fb", "typing", "read_delay", "token_mode"):
            if k in b:
                set_setting(k, b[k], scope)
        if b.get("paused") in (1, "1", True):
            for k in list(timers):
                if not scope or acct_of(k) == scope:
                    cancel_timer(k)
        return {"ok": True}
    if path == "/api/settings/reset":
        if b.get("account") not in ACCOUNTS:
            return {"error": "compte inconnu"}
        x("DELETE FROM account_settings WHERE account=? AND k NOT IN ('style_profile','style_n')", (b["account"],))
        log("info", f"[{b['account']}] réglages propres au compte réinitialisés (valeurs générales)")
        return {"ok": True}
    if path == "/api/chat/settings":
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
    if path == "/api/draft":
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
    if path == "/api/send":
        text = str(b.get("text") or "").strip()
        if not text or not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "message vide ou conversation inconnue"}
        return {"ok": send_text(b["key"], text, "owner")}
    if path == "/api/chat/import":
        if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "conversation inconnue"}
        return {"ok": run_bg("import", import_history, b["key"], max(1, min(int(b.get("pages", 10)), 30)))}
    if path == "/api/chat/add":
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
    if path == "/api/history/enroll":
        pin = str(b.get("pin") or "")
        if not b.get("confirm"):
            return {"error": "confirmation requise"}
        if not (len(pin) == 6 and pin.isdigit()):
            return {"error": "le PIN doit faire exactement 6 chiffres"}
        acct = ACCOUNTS.get(b.get("account") or default_account())
        if not acct or not acct.state.get("e2ee"):
            return {"error": "le canal chiffré n'est pas connecté"}
        acct.state["history"] = "enrolling"
        ok = acct.send({"op": "history_enroll", "pin": pin})
        pin = ""  # le PIN n'est ni stocké ni journalisé
        log("info", "Restauration de l'historique chiffré demandée (PIN transmis au client local, non conservé)")
        return {"ok": ok}
    if path == "/api/chat/prepare":
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
    if path == "/api/chat/prepare/discard":
        PREPARED.pop(b["key"], None)
        return {"ok": True}
    if path == "/api/message/edit":
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
    if path == "/api/chat/memory/refresh":
        def _mem(k=b["key"]):
            with task("Mise à jour de la mémoire de la conversation", key="memory"):
                tp(detail="le LLM relit la conversation")
                try:
                    update_memory(k, force=True)
                except Exception as ex:
                    log("error", f"Mémoire : {ex}", k)
        threading.Thread(target=_mem, daemon=True).start()
        return {"ok": True}
    if path == "/api/chat/sync":
        if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "conversation inconnue"}
        with task("Synchronisation de la conversation", key="sync1"):
            n = sync_many([b["key"]])
        log("info", f"Synchronisation manuelle : {n} message(s) de plus", b["key"])
        return {"ok": True, "new": n}
    if path == "/api/sync/all":
        ph, names = _in(mine())
        keys = [r["key"] for r in q(f"SELECT key FROM chats WHERE is_group=0 AND account IN ({ph}) AND (enabled=1 OR last_ts>?) ORDER BY enabled DESC, last_ts DESC LIMIT 40",
                                    (*names, NOW() - 3 * 86_400_000))]
        def go():
            n = sync_many(keys)
            log("info", f"Synchronisation complète : {n} message(s) rattrapé(s) sur {len(keys)} conversation(s)")
        return {"ok": run_bg("sync", go), "count": len(keys)}
    if path == "/api/chat/raise_limit":
        r = q("SELECT max_per_hour FROM chats WHERE key=?", (b["key"],))
        if not r:
            return {"error": "conversation inconnue"}
        new = min(100, r[0]["max_per_hour"] + 10)
        x("UPDATE chats SET max_per_hour=?, attention=0, attention_note='' WHERE key=?", (new, b["key"]))
        log("info", f"Limite horaire relevée à {new} réponses/h", b["key"])
        return {"ok": True, "max": new}
    if path == "/api/chat/unmute":
        if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "conversation inconnue"}
        x("UPDATE chats SET unmute_ts=? WHERE key=?", (NOW(), b["key"]))
        log("info", "Silence ignoré : le LLM peut de nouveau répondre ici", b["key"])
        return {"ok": True}
    if path == "/api/chat/preview":
        with task("Aperçu de la réponse", key="preview"):
            tp(detail="le LLM rédige (rien n'est envoyé)")
            return preview_reply(b["key"])
    if path == "/api/chat/send_preview":
        text = str(b.get("text") or "").strip()[:1500]
        if not text or not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "texte vide ou conversation inconnue"}
        cancel_timer(b["key"])
        ok = send_text(b["key"], text, "llm")
        return {"ok": ok} if ok else {"error": "envoi impossible (client arrêté ?)"}
    if path == "/api/chat/force":
        with task("Réponse du LLM" if b.get("send", True) else "Brouillon du LLM", key="force"):
            tp(detail="lecture du contexte, rédaction, contrôles de sécurité")
            return force_reply(b["key"], bool(b.get("send", True)), str(b.get("hint") or ""))
    if path == "/api/chat/pin":
        if not q("SELECT 1 FROM chats WHERE key=?", (b.get("key"),)):
            return {"error": "conversation inconnue"}
        x("UPDATE chats SET pinned=? WHERE key=?", (1 if b.get("pinned") else 0, b["key"]))
        return {"ok": True}
    if path == "/api/chat/delete":
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
    if path == "/api/chat/rename":
        name = str(b.get("name") or "").strip()[:80]
        if not q("SELECT 1 FROM chats WHERE key=?", (b["key"],)):
            return {"error": "conversation inconnue"}
        x("UPDATE chats SET name=? WHERE key=?", (name, b["key"]))
        return {"ok": True}
    if path == "/api/names/resolve":
        ph, names = _in(mine())
        x(f"UPDATE chats SET lookup_ts=0 WHERE (name='' OR name IS NULL) AND account IN ({ph})", names)  # nouvelle tentative sur les conversations sans nom
        return {"ok": run_bg("names", resolve_names, set(names))}
    if path == "/api/accounts/ext_code":
        try:
            return {"ok": True, "code": ext_new_code(cur_name())}
        except ValueError as ex:
            return {"error": str(ex)}
    if path == "/api/accounts/login/start":
        return start_login(cur_name(), (b.get("w"), b.get("h")))
    if path == "/api/accounts/login/input":
        return login_input(cur_name(), b)
    if path == "/api/accounts/login/cancel":
        info = LOGIN.get(_lkey(cur_name()))
        if info and info["proc"] and info["proc"].poll() is None:
            info["state"] = "cancelled"
            info["proc"].terminate()
        return {"ok": True}
    if path == "/api/accounts/import_curl":
        jar = parse_curl_cookies(str(b.get("curl") or ""))
        if not jar:
            return {"error": "cookies introuvables : colle une requête « Copy as cURL » faite sur messenger.com une fois connecté"}
        try:
            name, reused = connect_account(jar, cur_name())
        except ValueError as ex:
            return {"error": str(ex)}
        return {"ok": True, "name": name, "reused": reused}
    if path == "/api/accounts/register_e2ee":
        acct = ACCOUNTS.get(b.get("name"))
        if not acct:
            return {"error": "compte inconnu"}
        if not b.get("confirm"):
            return {"error": "confirmation requise : cette action ajoute un appareil chiffré sur le compte Messenger"}
        if has_registered_device(acct.dir):
            return {"error": "un appareil chiffré existe déjà pour ce compte : aucun nouvel enregistrement n'est nécessaire"}
        acct.args = ["-register-e2ee"]
        if acct.proc and acct.proc.poll() is None:
            acct.proc.terminate()   # la boucle relance le client avec l'enregistrement (une seule fois)
        log("info", f"[{acct.name}] enregistrement de l'appareil chiffré demandé")
        return {"ok": True}
    if path == "/api/accounts/remove":
        name = b.get("name")
        if name not in ACCOUNTS:
            return {"error": "compte inconnu"}
        if not b.get("confirm"):
            return {"error": "confirmation requise"}
        for k in [k for k in timers if acct_of(k) == name]:
            cancel_timer(k)
        ACCOUNTS[name].shutdown()
        del ACCOUNTS[name]
        save_accounts()
        log("info", f"Compte « {name} » retiré (ses fichiers sont conservés sur le disque)")
        return {"ok": True}
    if path == "/api/threads/load":
        return {"ok": all([a.send({"op": "threads"}) for a in ACCOUNTS.values() if a.name in mine()])}
    if path == "/api/style/analyze":
        if b.get("account") and b["account"] not in ACCOUNTS:
            return {"error": "compte inconnu"}
        threading.Thread(target=analyze_style, args=(b.get("account"),), daemon=True).start()
        return {"ok": True}
    if path == "/api/style/learn":
        if b.get("account") and b["account"] not in ACCOUNTS:
            return {"error": "compte inconnu"}
        return {"ok": run_bg("learn", learn_all, b.get("account"))}
    if path == "/api/clear_attention":
        x("UPDATE chats SET attention=0, attention_note='' WHERE key=?", (b["key"],))
        return {"ok": True}
    return {"error": "route inconnue"}


KEY_ROUTES = {"/api/send", "/api/chat/import", "/api/chat/prepare", "/api/chat/prepare/discard", "/api/message/edit", "/api/chat/sync", "/api/chat/raise_limit",
              "/api/chat/unmute", "/api/chat/preview", "/api/chat/send_preview", "/api/chat/force", "/api/chat/pin", "/api/chat/delete", "/api/chat/rename",
              "/api/clear_attention", "/api/chat/settings", "/api/chat/memory/refresh"}


ACCT_ROUTES = {"/api/settings/reset": "account", "/api/accounts/register_e2ee": "name", "/api/accounts/remove": "name"}


DEFAULT_ACCT_ROUTES = {"/api/chat/add", "/api/history/enroll", "/api/style/analyze", "/api/style/learn"}


def post(path, b):
    """Point d'entrée des actions : vérifie que l'utilisateur possède bien ce qu'il touche, puis exécute."""
    if path.startswith("/api/users") or path == "/api/me/password":
        return users_api(path, b)
    if AUTH.enabled:
        if not isinstance(b, dict):
            return {"error": "requête invalide"}
        if path in KEY_ROUTES:
            if not own_chat(b.get("key")):
                return {"error": "conversation inconnue"}
        elif path == "/api/draft":
            d = q("SELECT chat_key FROM drafts WHERE id=?", (b.get("id"),))
            if not d or not own_chat(d[0]["chat_key"]):
                return {"error": "brouillon introuvable"}
        elif path in ACCT_ROUTES:
            n = b.get(ACCT_ROUTES[path])
            if not isinstance(n, str) or n not in mine():
                return {"error": "compte inconnu"}
        elif path in DEFAULT_ACCT_ROUTES:
            n = b.get("account") or next(iter(sorted(mine())), None)
            if not isinstance(n, str) or n not in mine():
                return {"error": "compte inconnu"}
            b = dict(b)
            b["account"] = n
        elif path == "/api/settings":
            sc = b.get("account") or None
            if sc:
                if not isinstance(sc, str) or sc not in mine():
                    return {"error": "compte inconnu"}
            elif not is_admin():   # pas de réglages « généraux » pour un utilisateur : on les applique à chacun de SES comptes
                for n in sorted(mine()):
                    _post(path, {**b, "account": n})
                return {"ok": True}
    return _post(path, b)
