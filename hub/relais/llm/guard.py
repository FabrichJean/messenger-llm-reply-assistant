"""Défenses : classifieur d'entrée, leurre, vérification des réponses avant envoi."""

import re
import time

from .. import security
from ..context import acct_of, log
from ..db import NOW, is_paused, q, setting, x
from .claude import call_claude
from .outbox import send_text
from .prompts import GUARD
from .timers import cancel_timer


def security_event(key, kind, detail):
    chat_key = key
    """Journalise un évènement de sécurité (sans le contenu) ; 3 messages suspects en 24 h => LLM désactivé pour ce contact."""
    x("INSERT INTO security_events(ts,chat_key,kind,detail) VALUES(?,?,?,?)", (NOW(), key, kind, detail))
    log("warn", f"Sécurité : {detail}", key)
    if kind == "input" and setting("attack_mode", acct_of(chat_key)) != "decoy":   # en mode leurre, le LLM n'est jamais désactivé
        n = q("SELECT COUNT(*) c FROM security_events WHERE chat_key=? AND kind='input' AND ts>?", (key, NOW() - 86_400_000))[0]["c"]
        if n >= 3:
            x("UPDATE chats SET enabled=0, attention=1, attention_note=? WHERE key=?",
              ("LLM désactivé automatiquement : messages suspects répétés de ce contact", key))
            cancel_timer(key)
            log("warn", "Sécurité : LLM désactivé pour ce contact (messages suspects répétés)", key)


def quiet_note(key, detail):
    """Niveau « discret » : on note l'évènement dans le journal, sans bannière ni blocage."""
    x("INSERT INTO security_events(ts,chat_key,kind,detail) VALUES(?,?,?,?)", (NOW(), key, "quiet", detail))
    log("info", f"Sécurité (non bloquant) : {detail}", key)


def classify_input(texts):
    """Second avis sémantique (LLM) sur les derniers messages du contact. -> (sûr, raison). Échec => non sûr (fail closed)."""
    nonce = security.new_nonce()
    lines = [security.clean_untrusted(t, 600) for t in texts[:6]]
    try:
        out = call_claude(security.CLASSIFIER_SYSTEM, security.classifier_prompt(lines, nonce), model="haiku", kind="classifier")
    except Exception as ex:
        return False, f"détecteur indisponible ({str(ex)[:50]})"
    return security.classifier_safe(out)


def generate_decoy(key, attack):
    """-> (texte ou None, raison du rejet). Sans effet de bord (n'envoie rien, n'écrit rien)."""
    strikes = q("SELECT COUNT(*) c FROM security_events WHERE chat_key=? AND kind='decoy' AND ts>?", (key, NOW() - 86_400_000))[0]["c"]
    try:
        nonce = security.new_nonce()
        system_decoy = security.DECOY_SYSTEM + (security.DECOY_ESCALATION if strikes >= 1 else "")
        out = call_claude(system_decoy, security.decoy_prompt(attack, nonce), kind="decoy").strip().strip('"').strip()
        ok, bad = security.check_decoy(out, attack_text=attack)
        if ok:
            v = call_claude(security.DECOY_JUDGE_SYSTEM, security.judge_prompt([f"Attaque : {security.clean_untrusted(attack, 300)}"], out, nonce), model="haiku", kind="judge")
            ok, bad = security.judge_ok(v)
            bad = "second contrôle : " + bad[:80]
    except Exception as ex:
        return None, f"leurre non généré ({str(ex)[:60]})"
    return (out, "") if ok else (None, bad)


def decoy_reply(key, chat, texts, why):
    """Au lieu du silence : une FAUSSE réponse sarcastique, générée sans aucun accès à tes instructions ni à ton historique.
    Retourne True si un leurre a été envoyé (ou mis en brouillon)."""
    if setting("attack_mode", chat["account"]) != "decoy" or is_paused(chat["account"]):
        return False
    since = NOW() - 3_600_000
    if q("SELECT COUNT(*) c FROM security_events WHERE chat_key=? AND kind='decoy' AND ts>?", (key, since))[0]["c"] >= 2:
        return False  # pas plus de 2 leurres par heure et par contact : on ne nourrit pas un attaquant acharné
    attack = texts[0] if texts else ""
    out, bad = generate_decoy(key, attack)
    if out is None:
        log("info", f"Leurre non envoyé ({bad}) : aucune réponse", key)
        return False
    x("INSERT INTO security_events(ts,chat_key,kind,detail) VALUES(?,?,?,?)", (NOW(), key, "decoy", why[:80]))
    if chat["mode"] == "draft":
        x("INSERT INTO drafts(chat_key,text,created) VALUES(?,?,?)", (key, out, NOW()))
        x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (f"message suspect ({why}) : réponse sarcastique proposée en brouillon", key))
        log("info", "Message suspect : réponse sarcastique en brouillon", key)
        return True
    time.sleep(min(len(out) * 0.04, 6))
    send_text(key, out, "llm", auto=True)
    x("UPDATE chats SET attention=0, attention_note='' WHERE key=?", (key,))
    log("info", f"Message suspect ({why}) : réponse sarcastique (leurre) envoyée", key)
    return True


def recent_untrusted(key, limit=6):
    """Messages du contact restés sans réponse (ou les derniers), non fiables."""
    last_own = q("SELECT MAX(ts) t FROM messages WHERE chat_key=? AND src IN ('owner','llm')", (key,))[0]["t"] or 0
    since = max(last_own, NOW() - 3 * 3_600_000)   # récents et sans réponse (les plus anciens sont masqués dans le prompt)
    rows = q("SELECT text FROM messages WHERE chat_key=? AND src='contact' AND deleted=0 AND ts>? ORDER BY ts DESC LIMIT ?", (key, since, limit))
    if not rows:
        rows = q("SELECT text FROM messages WHERE chat_key=? AND src='contact' AND deleted=0 ORDER BY ts DESC LIMIT 1", (key,))
    return [r["text"] for r in rows]


def vet_reply(chat, system, user, reply):
    """Filtre de sortie + second contrôle. -> (ok, raison)."""
    level = setting("security_level", chat["account"])
    if level == "off":
        return True, ""
    trusted = "\n".join([setting("persona", chat["account"]), chat["instructions"], setting("owner", chat["account"])])
    m = re.search(r"CANARI-[0-9a-f]{12}", system + "\n" + user)
    ok, why = security.check_reply(reply, trusted, GUARD, canary=m.group(0) if m else None)
    if level == "quiet":
        if not ok:
            quiet_note(chat["key"], f"réponse inhabituelle ({why}) envoyée quand même")
        return True, ""
    if not ok:
        return False, why
    if setting("judge", chat["account"]) == "1" and not chat.get("trusted"):
        try:
            nonce = security.new_nonce()
            tail = [l for l in user.splitlines() if l.startswith("[")][-8:]
            verdict = call_claude(security.JUDGE_SYSTEM, security.judge_prompt(tail, reply, nonce), model="haiku", kind="judge")
        except Exception as ex:
            return False, f"contrôle de sécurité indisponible ({str(ex)[:60]})"  # fail closed
        ok, detail = security.judge_ok(verdict)
        if not ok:
            return False, "second contrôle : " + (detail or "refus")[:120]
    return True, ""


def hold_for_review(key, reply, why):
    """Réponse jugée risquée : on ne l'envoie pas, elle devient un brouillon et tu es prévenu."""
    x("INSERT INTO drafts(chat_key,text,created) VALUES(?,?,?)", (key, reply[:1500], NOW()))
    x("UPDATE chats SET attention=1, attention_note=? WHERE key=?", (f"réponse bloquée par le filtre de sécurité : {why}", key))
    security_event(key, "output", f"réponse bloquée ({why})")
