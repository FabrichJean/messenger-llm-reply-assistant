"""Lecture de l'état pour l'interface : état général, statistiques, conversation."""

import hashlib
import time
from pathlib import Path

from ..accounts import ACCOUNTS, has_registered_device, mine
from ..attachments import attach_list
from ..config import LOGIN_PY, LOGIN_SCRIPT, REMOTE_LOGIN
from ..context import AUTH, LOG, cur, cur_name, is_admin
from ..db import NOW, PRIVATE_KEYS, SETTING_DEFAULTS, _in, q, setting
from ..llm.outbox import llm_count_last_hour, owner_recent_ts
from ..llm.prepare import PREPARED
from ..llm.style import STYLE_BUSY, owner_count
from ..sync import SYNC_INFO
from ..tasks import BG, tasks_view


CHAT_FIELDS = ("key,name,last_ts,last_text,enabled,mode,is_group,attention,attention_note,route,account,instructions,max_per_hour,delay_s,takeover_off,unmute_ts,trusted,pinned")


def api_state():
    vis = {n: a for n, a in ACCOUNTS.items() if n in mine()}
    ph, names = _in(vis)
    chats = q(f"SELECT {CHAT_FIELDS} FROM chats WHERE account IN ({ph}) ORDER BY last_ts DESC LIMIT 400", names)
    mk = f"chat_key IN (SELECT key FROM chats WHERE account IN ({ph}))"
    pend = {r["chat_key"]: r["c"] for r in q(f"SELECT chat_key, COUNT(*) c FROM drafts WHERE status='pending' AND {mk} GROUP BY chat_key", names)}
    pics = {r["key"]: r["pic"] for r in q(f"SELECT key, pic FROM chats WHERE pic<>'' AND account IN ({ph})", names)}
    counts = {r["chat_key"]: r["c"] for r in q(f"SELECT chat_key, COUNT(*) c FROM messages WHERE {mk} GROUP BY chat_key", names)}
    # « non lues » : messages reçus depuis ta dernière réponse (la tienne ou celle du LLM), sur 30 jours
    unread = {r["chat_key"]: r["c"] for r in q(
        "SELECT m.chat_key, COUNT(*) c FROM messages m WHERE m.src='contact' AND m.deleted=0 AND m.ts>? AND m.ts > "
        "COALESCE((SELECT MAX(o.ts) FROM messages o WHERE o.chat_key=m.chat_key AND o.src IN ('owner','llm')),0) "
        f"AND m.{mk} GROUP BY m.chat_key",
        (NOW() - 30 * 86_400_000, *names))}
    for c in chats:
        c["unread"] = min(unread.get(c["key"], 0), 99)
        c["n_msgs"] = counts.get(c["key"], 0)
        c["pic"] = hashlib.sha1(pics[c["key"]].encode()).hexdigest()[:10] if c["key"] in pics else ""
        c["drafts"] = pend.get(c["key"], 0)
        c["name"] = c["name"] or c["key"].split(":")[-1]
    st = {k: setting(k) for k in SETTING_DEFAULTS}
    if AUTH.enabled:
        for k in PRIVATE_KEYS:
            st[k] = SETTING_DEFAULTS[k]
        if not is_admin():   # « pause générale » d'un utilisateur = tous SES comptes en pause
            st["paused"] = "1" if st["paused"] == "1" or (vis and all(setting("paused", n) == "1" for n in vis)) else "0"
    me = cur()
    admin = (not AUTH.enabled) or is_admin()
    visible_log = [e for e in LOG if (e.get("acct") in vis) or (admin and not e.get("acct"))]
    return {
        "settings": st,
        "accounts": [{"name": a.name, "label": a.label or a.name, "has_device": has_registered_device(a.dir), **a.state} for a in vis.values()],
        "sync": dict(SYNC_INFO), "llm_last_hour": sum(llm_count_last_hour(account=n) for n in vis), "owner_msgs": sum(owner_count(n) for n in vis),
        "busy": {"style": any(n in STYLE_BUSY for n in vis), "import": BG.get(cur_name(), "")},
        "account_settings": {a: {r["k"]: r["v"] for r in q("SELECT k,v FROM account_settings WHERE account=?", (a,)) if r["k"] != "__x"} for a in vis},
        "owner_msgs_by_account": {a: owner_count(a) for a in vis},
        "chats": chats, "log": [{k: v for k, v in e.items() if k != "acct"} for e in visible_log][-80:], "tasks": tasks_view(),
        "can_login": LOGIN_PY.exists() and LOGIN_SCRIPT.exists(), "login_remote": REMOTE_LOGIN, "auth": AUTH.enabled,
        "me": {"name": me["name"], "role": me["role"]} if (me and AUTH.enabled) else None,
    }


def usage_summary(since, names=None):
    """Consommation du LLM depuis `since` : appels, tokens (entrée = neuf + cache lu + cache écrit), sortie, part servie par le cache, coût."""
    kinds = {}
    ph, args = _in(names) if names is not None else ("", ())
    flt = f" AND account IN ({ph})" if names is not None else ""
    for r in q(f"SELECT kind, COUNT(*) n, SUM(input) i, SUM(cache_read) cr, SUM(cache_write) cw, SUM(output) o, SUM(cost) c FROM llm_usage WHERE ts>?{flt} GROUP BY kind", (since, *args)):
        kinds[r["kind"]] = {"calls": r["n"], "in": (r["i"] or 0) + (r["cr"] or 0) + (r["cw"] or 0), "cached": r["cr"] or 0, "out": r["o"] or 0, "cost": round(r["c"] or 0, 4)}
    tot = {k: sum(v[k] for v in kinds.values()) for k in ("calls", "in", "cached", "out", "cost")}
    tot["cost"] = round(tot["cost"], 4)
    tot["cache_pct"] = round(100 * tot["cached"] / tot["in"]) if tot["in"] else 0
    return {"total": tot, "kinds": kinds}


def api_stats():
    """Chiffres d'activité (comptages seulement, jamais de contenu), limités aux comptes de l'utilisateur."""
    vis = {n: a for n, a in ACCOUNTS.items() if n in mine()}
    ph, names = _in(vis)
    ck = f"(SELECT key FROM chats WHERE account IN ({ph}))"
    since = NOW() - 14 * 86_400_000
    rows = q(f"SELECT strftime('%Y-%m-%d', ts/1000, 'unixepoch', 'localtime') d, src, COUNT(*) c FROM messages WHERE ts>? AND deleted=0 AND chat_key IN {ck} GROUP BY d, src", (since, *names))
    days = {}
    for r in rows:
        days.setdefault(r["d"], {"contact": 0, "owner": 0, "llm": 0})[r["src"] if r["src"] in ("contact", "owner", "llm") else "contact"] += r["c"]
    series = []
    for i in range(13, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        series.append({"d": d, **days.get(d, {"contact": 0, "owner": 0, "llm": 0})})
    disk = 0
    for a in vis.values():
        try:
            disk += sum(f.stat().st_size for f in (Path(a.dir) / "media").iterdir() if f.is_file())
        except OSError:
            pass
    one = lambda sql, a=(): q(sql, a)[0]["c"]
    return {
        "series": series,
        "chats": one(f"SELECT COUNT(*) c FROM chats WHERE account IN ({ph})", names), "chats_on": one(f"SELECT COUNT(*) c FROM chats WHERE enabled=1 AND account IN ({ph})", names),
        "messages": one(f"SELECT COUNT(*) c FROM messages WHERE deleted=0 AND chat_key IN {ck}", names), "llm_total": one(f"SELECT COUNT(*) c FROM messages WHERE src='llm' AND chat_key IN {ck}", names),
        "llm_hour": sum(llm_count_last_hour(account=n) for n in vis), "drafts": one(f"SELECT COUNT(*) c FROM drafts WHERE status='pending' AND chat_key IN {ck}", names),
        "attachments": one(f"SELECT COUNT(*) c FROM attachments WHERE account IN ({ph})", names), "media_bytes": disk,
        "attacks_7d": one(f"SELECT COUNT(*) c FROM security_events WHERE ts>? AND chat_key IN {ck}", (NOW() - 7 * 86_400_000, *names)),
        "usage": {lab: usage_summary(NOW() - ms, names) for lab, ms in (("24h", 86_400_000), ("7j", 7 * 86_400_000))},
    }


def api_chat(key):
    rows = q(f"SELECT {CHAT_FIELDS},memory FROM chats WHERE key=?", (key,))
    if not rows:
        return None
    msgs = q("SELECT id,ts,sender,text,src,edited,deleted,local_edit FROM messages WHERE chat_key=? ORDER BY ts DESC LIMIT 150", (key,))[::-1]
    for m in msgs:
        if m["deleted"]:
            m["text"] = ""  # le contenu d'un message supprimé n'est plus affiché
    attach_list(key, msgs)
    drafts = q("SELECT id,text,created FROM drafts WHERE chat_key=? AND status='pending' ORDER BY id", (key,))
    c = rows[0]
    c["name"] = c["name"] or key.split(":")[-1]
    left = int(setting("takeover_min", c["account"])) * 60_000 - (NOW() - owner_recent_ts(key, c))
    c["muted_min"] = int(left // 60_000) + 1 if left > 0 and c["enabled"] else 0
    c["llm_hour"] = llm_count_last_hour(key)
    pr = q("SELECT pic FROM chats WHERE key=? AND pic<>''", (key,))
    c["pic"] = hashlib.sha1(pr[0]["pic"].encode()).hexdigest()[:10] if pr else ""
    return {"chat": c, "messages": msgs, "drafts": drafts, "prepared": PREPARED.get(key)}
