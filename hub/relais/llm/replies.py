"""Pipeline de réponse automatique : minuteries, génération, humanisation, envoi."""

import random
import threading
import time

from .. import security
from . import humanize as hz
from ..accounts import ACCOUNTS
from ..context import log
from ..db import NOW, is_paused, q, setting, x
from .claude import LLM_SEM, call_claude
from .guard import classify_input, decoy_reply, hold_for_review, quiet_note, recent_untrusted, security_event, vet_reply
from .memory_update import _bg_memory
from .outbox import llm_count_last_hour, owner_recent_ts, send_text
from .prompts import build_prompts, split_skip
from .timers import cancel_timer, timers, versions


def schedule_reply(key, delay_s):
    cancel_timer(key)
    ver = versions[key]
    t = threading.Timer(max(0, delay_s), run_reply, args=(key, ver))
    t.daemon = True
    timers[key] = t
    t.start()


def reading_delay(chat):
    """Temps qu'un humain mettrait à LIRE les messages en attente avant de se mettre à écrire : une courte attention, plus la lecture
    (~15 caractères par seconde), avec un peu d'aléatoire ; plafonné par le réglage « délai de lecture » (0 = aucun)."""
    cap = max(0, min(int(setting("read_delay", chat["account"]) or 0), 60))
    if not cap:
        return 0.0
    last = q("SELECT MAX(ts) t FROM messages WHERE chat_key=? AND src IN ('owner','llm')", (chat["key"],))[0]["t"] or 0
    rows = q("SELECT text FROM messages WHERE chat_key=? AND src='contact' AND deleted=0 AND ts>? ORDER BY ts DESC LIMIT 8", (chat["key"], last))
    chars = sum(min(len(r["text"] or ""), 400) for r in rows if not (r["text"] or "").startswith("[") )
    return round(min(cap, 1.2 + chars / 15.0 + random.uniform(0.3, 2.2)), 1)


class Typing:
    """Affiche « est en train d'écrire » chez l'interlocuteur pendant que le LLM prépare une réponse qui sera ENVOYÉE
    (jamais pour un brouillon). Réémis toutes les 4 s tant que ça dure, retiré dès que le message part ou que la tâche s'arrête."""
    def __init__(self, key):
        self.key, self.chat, self.on, self.ev, self.th = key, None, False, threading.Event(), None

    def start(self, chat, force=False):
        if self.on or (chat["mode"] == "draft" and not force) or chat["is_group"] or setting("typing", chat["account"]) != "1":
            return
        self.chat, self.on = chat, True
        self._send(True)
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _loop(self):
        while not self.ev.wait(4):
            self._send(True)

    def _send(self, on):
        c = self.chat
        acct = ACCOUNTS.get(c["account"]) if c else None
        if not acct:
            return
        if c["route"] == "e2ee" and c["jid"]:
            acct.send({"op": "typing", "chat": c["jid"], "on": on})
        else:
            acct.send({"op": "typing", "thread": c["thread"], "kind": int(c.get("kind") or 0) or 1, "on": on})

    def stop(self):
        if not self.on:
            return
        self.on = False
        self.ev.set()
        self._send(False)


def run_reply(key, ver):
    ty = Typing(key)
    try:
        _run_reply(key, ver, ty)
    finally:
        ty.stop()


def _humanize(chat, reply, system, user, lenient=False):
    """Dernier filet : longueur proportionnée, pas de répétition d'un message déjà envoyé, emojis mesurés. Retourne None si rien d'utile à ajouter."""
    key, acct = chat["key"], chat["account"]
    own = [r["text"] for r in q("SELECT text FROM messages WHERE chat_key=? AND src='owner' AND deleted=0 AND length(text)>1 ORDER BY ts DESC LIMIT 40", (key,))]
    if len(own) < 6:
        own = [r["text"] for r in q("SELECT m.text AS text FROM messages m JOIN chats c ON c.key=m.chat_key WHERE m.src='owner' AND m.deleted=0 "
                                    "AND length(m.text)>1 AND c.account=? ORDER BY m.ts DESC LIMIT 60", (acct,))]
    lastc = (recent_untrusted(key, 1) or [""])[0]
    tw = hz.target_words(own, lastc)
    if lenient:   # réponse franche à « tu es une IA ? » : elle doit rester complète
        tw = max(tw, 14)
    rate = hz.emoji_rate(own) if len(own) >= 6 else 0.3
    recent = [r["text"] for r in q("SELECT text FROM messages WHERE chat_key=? AND src IN ('owner','llm') AND deleted=0 AND ts>? ORDER BY ts DESC LIMIT 4",
                                   (key, NOW() - 36 * 3_600_000))]

    def dup(t):
        return hz.words(t) >= 4 and any(hz.similarity(t, r) >= 0.6 for r in recent)

    def problems(t):
        pb = []
        if hz.words(t) > tw * 1.6:
            pb.append(f"trop longue : {tw} mots au maximum, une seule courte phrase")
        if dup(t):
            pb.append("trop semblable à un message déjà envoyé : dis quelque chose de très différent et très court, ou [SKIP] s'il n'y a rien à ajouter")
        if hz.repeated_opener(t, recent):
            pb.append("commence par les mêmes mots que tes derniers messages (tic d'automate) : commence autrement, directement par le fond, sans « haha ok »")
        return pb
    for _ in range(2):
        pb = problems(reply)
        if not pb:
            break
        try:
            new = call_claude(system, user + "\nCorrection : ta réponse précédente est " + " ; ".join(pb) + ".", account=acct).strip().strip('"').strip()
        except Exception:
            break
        if not new:
            break
        if split_skip(new)[0]:
            return None
        reply = new
    if dup(reply):
        return None
    if hz.repeated_opener(reply, recent):
        reply = hz.strip_opener(reply)   # dernier filet : on retire d'abord l'interjection d'ouverture répétée…
    if hz.words(reply) > tw * 1.6:
        reply = hz.cut_sentences(reply, tw)   # …puis on raccourcit si besoin
    reply = hz.drop_repeated_emojis(reply, recent)
    return hz.limit_emojis(reply, 0 if rate < 0.15 else 1).strip() or None


def _run_reply(key, ver, ty):
    with LLM_SEM:
        for _attempt in range(3):
            if versions.get(key) != ver:
                return  # un message plus récent a relancé le minuteur
            chat = (q("SELECT * FROM chats WHERE key=?", (key,)) or [None])[0]
            if not chat or not chat["enabled"] or chat["is_group"] or is_paused(chat["account"]):
                return
            if NOW() - owner_recent_ts(key, chat) < int(setting("takeover_min", chat["account"])) * 60_000:
                log("info", "Reprise en main récente : le LLM reste muet", key)
                return
            n_chat, n_all = llm_count_last_hour(key), llm_count_last_hour(account=chat["account"])
            if n_chat >= chat["max_per_hour"] or n_all >= int(setting("max_per_hour_global", chat["account"])):
                which = (f"cette conversation {n_chat}/{chat['max_per_hour']}" if n_chat >= chat["max_per_hour"]
                         else f"globale {n_all}/{setting('max_per_hour_global', chat['account'])}")
                x("UPDATE chats SET attention=1, attention_note=? WHERE key=?",
                  (f"limite de réponses par heure atteinte ({which}) : augmente-la dans les réglages", key))
                log("warn", f"Limite de réponses par heure atteinte ({which})", key)
                return
            level = setting("security_level", chat["account"])
            susp = None if (chat["trusted"] or level == "off") else security.suspicious_input(recent_untrusted(key))
            if susp and level == "quiet":
                quiet_note(key, f"message suspect ({susp}) — réponse non bloquée")
                susp = None
            if susp:
                security_event(key, "input", f"message suspect ({susp})")
                if decoy_reply(key, chat, recent_untrusted(key), susp):
                    return
                x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (f"message suspect ({susp}) : aucune réponse automatique", key))
                return
            ai_q = any(hz.asks_if_bot(t) for t in recent_untrusted(key)[:2])
            verdict = {}
            watcher = None
            if level == "strict" and not chat["trusted"] and setting("classifier", chat["account"]) == "1":
                texts = recent_untrusted(key)
                watcher = threading.Thread(target=lambda: verdict.update(r=classify_input(texts)), daemon=True)
                watcher.start()  # en parallèle de la génération : pas de latence en plus
            system, user = build_prompts(chat, hint=("L'interlocuteur demande ou taquine pour savoir s'il parle à une IA : réponds franchement et simplement, en une phrase "
                                                     "naturelle, que tu es l'assistant automatique de " + setting("owner", chat["account"]) + " qui répond à sa place.") if ai_q else "")
            # la génération démarre tout de suite (pas de latence en plus) ; pendant ce temps on « lit » les messages,
            # et l'indicateur « en train d'écrire » n'apparaît qu'après ce délai de lecture
            gen = {}

            def _gen(system=system, user=user, acct=chat["account"]):
                try:
                    gen["r"] = call_claude(system, user, account=acct)
                except Exception as ex:
                    gen["e"] = ex
            gth = threading.Thread(target=_gen, daemon=True)
            gth.start()
            rd = reading_delay(chat)
            if rd > 0:
                log("info", f"Lecture des messages : {rd} s avant d'écrire", key)
                end = time.time() + rd
                while time.time() < end:
                    if versions.get(key) != ver:
                        return  # un message plus récent a relancé le minuteur
                    time.sleep(0.25)
            ty.start(chat)   # le contact voit « en train d'écrire » à partir d'ici
            gth.join(150)
            if "e" in gen or "r" not in gen:
                log("error", f"Claude CLI: {gen.get('e', 'pas de réponse')}", key)
                return
            reply = gen["r"]
            if watcher:
                watcher.join(90)
                safe, why_ai = verdict.get("r", (False, "détecteur sans réponse"))
                if not safe:
                    security_event(key, "input", f"message suspect (analyse sémantique : {why_ai[:90]})")
                    if decoy_reply(key, chat, texts, "analyse sémantique"):
                        return
                    x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (f"message jugé suspect par l'analyse sémantique ({why_ai[:90]}) : aucune réponse automatique", key))
                    return
            if versions.get(key) != ver:
                return
            last_in = q("SELECT MAX(ts) t FROM messages WHERE chat_key=? AND src='contact'", (key,))[0]["t"] or 0
            if last_in > NOW() - 1500 and _attempt < 2:
                continue  # un message vient d'arriver pendant la génération : on régénère
            break
        reply = reply.strip().strip('"').strip()
        alert = reply.upper().startswith("[ALERTE]")
        if alert:
            reply = reply[8:].strip()
            alert_note = "⚠ situation grave signalée (urgence, danger ou détresse) : réponds-lui toi-même dès que possible"
            x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (alert_note, key))
            log("warn", "Situation grave signalée par le contact : message d'empathie envoyé, à toi de prendre le relais", key)
        skip, why = split_skip(reply)
        is_attack = reply.upper().startswith("[ATTAQUE]") or (skip and security.looks_like_attack(why))
        if is_attack and not chat["trusted"] and level != "off":
            security_event(key, "input", "manipulation détectée par le LLM")
            if decoy_reply(key, chat, recent_untrusted(key), "manipulation détectée"):
                return
            x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", ("manipulation détectée : aucune réponse automatique", key))
            return
        if not reply or skip or reply.upper().startswith("[ATTAQUE]"):
            x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (why, key))
            log("info", "Le LLM passe la main (à traiter par toi)", key)
            return
        reply = reply[:1500]
        reply = reply if alert else _humanize(chat, reply, system, user, lenient=ai_q)
        if not reply:
            log("info", "Rien d'utile à ajouter (réponse répétitive ou trop longue pour ce contexte) : le LLM se tait", key)
            return
        ok_reply, why_blocked = vet_reply(chat, system, user, reply)
        if not ok_reply:
            hold_for_review(key, reply, why_blocked)
            return
        if chat["mode"] == "draft":
            x("INSERT INTO drafts(chat_key,text,created) VALUES(?,?,?)", (key, reply, NOW()))
            log("info", "Brouillon prêt", key)
            return
        time.sleep(min(len(reply) * 0.04, 8))  # frappe « humaine » : l'indicateur reste affiché pendant ce temps
        if versions.get(key) != ver:
            return
        ty.stop()
        send_text(key, reply, "llm", auto=True)
        if alert:   # l'enregistrement du message envoyé remet « à traiter » à zéro : on le réapplique pour que le propriétaire soit bien alerté
            x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (alert_note, key))
        threading.Thread(target=_bg_memory, args=(key,), daemon=True).start()
