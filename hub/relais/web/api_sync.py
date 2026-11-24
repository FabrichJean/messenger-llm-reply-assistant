"""Routes de synchronisation, résolution des noms et apprentissage du style."""

import threading
from ..accounts import ACCOUNTS, mine
from ..context import log
from ..db import NOW, _in, q, x
from ..llm.style import analyze_style, learn_all
from ..sync import resolve_names, sync_many
from ..tasks import run_bg


def sync_all(b):
    # POST /api/sync/all
    ph, names = _in(mine())
    keys = [r["key"] for r in q(f"SELECT key FROM chats WHERE is_group=0 AND account IN ({ph}) AND (enabled=1 OR last_ts>?) ORDER BY enabled DESC, last_ts DESC LIMIT 40",
                                (*names, NOW() - 3 * 86_400_000))]
    def go():
        n = sync_many(keys)
        log("info", f"Synchronisation complète : {n} message(s) rattrapé(s) sur {len(keys)} conversation(s)")
    return {"ok": run_bg("sync", go), "count": len(keys)}


def names_resolve(b):
    # POST /api/names/resolve
    ph, names = _in(mine())
    x(f"UPDATE chats SET lookup_ts=0 WHERE (name='' OR name IS NULL) AND account IN ({ph})", names)  # nouvelle tentative sur les conversations sans nom
    return {"ok": run_bg("names", resolve_names, set(names))}


def threads_load(b):
    # POST /api/threads/load
    return {"ok": all([a.send({"op": "threads"}) for a in ACCOUNTS.values() if a.name in mine()])}


def style_analyze(b):
    # POST /api/style/analyze
    if b.get("account") and b["account"] not in ACCOUNTS:
        return {"error": "compte inconnu"}
    threading.Thread(target=analyze_style, args=(b.get("account"),), daemon=True).start()
    return {"ok": True}


def style_learn(b):
    # POST /api/style/learn
    if b.get("account") and b["account"] not in ACCOUNTS:
        return {"error": "compte inconnu"}
    return {"ok": run_bg("learn", learn_all, b.get("account"))}


ROUTES = {
    "/api/sync/all": sync_all,
    "/api/names/resolve": names_resolve,
    "/api/threads/load": threads_load,
    "/api/style/analyze": style_analyze,
    "/api/style/learn": style_learn,
}
