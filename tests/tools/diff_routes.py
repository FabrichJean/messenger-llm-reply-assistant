#!/usr/bin/env python3
"""Test DIFFÉRENTIEL des routes POST : rejoue le même scénario sur deux versions du hub et compare tout.

Sert à prouver qu'une refonte de la couche web ne change aucun comportement : pour chaque route, des appels valides
ET invalides ; on compare le code HTTP, le JSON, l'état de la base après chaque appel et les ordres reçus par le client.

    python3 tests/tools/diff_routes.py <ancien dossier du dépôt> <nouveau dossier du dépôt>

L'ancienne version est exécutée DEUX fois : les requêtes dont le résultat varie d'une exécution à l'autre
(tâches de fond, minuteries) sont signalées « instables » et exclues de la comparaison.
"""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hubtest.harness import TestHub

VERBOSE = "-v" in sys.argv
A = "demo:"
SCENARIO = [
    ("/api/settings", {"paused": "1"}), ("/api/settings", {"paused": "0"}), ("/api/settings", {"owner": "Camille", "account": "demo"}),
    ("/api/settings", {"account": "nope"}), ("/api/settings", {}), ("/api/settings", {"model": "haiku", "judge": "0", "security_level": "strict"}),
    ("/api/settings/reset", {"account": "demo"}), ("/api/settings/reset", {"account": "nope"}), ("/api/settings/reset", {}),
    ("/api/chat/settings", {"key": A + "101", "mode": "draft", "delay_s": 3, "max_per_hour": 999, "instructions": "consigne", "memory": "- [identité|confirmé] A", "trusted": True, "takeover_off": True}),
    ("/api/chat/settings", {"key": A + "101", "enabled": False}), ("/api/chat/settings", {"key": A + "101", "enabled": True}),
    ("/api/chat/settings", {"key": A + "104", "enabled": True}), ("/api/chat/settings", {"key": "nope"}), ("/api/chat/settings", {}),
    ("/api/chat/settings", {"key": A + "101", "delay_s": "abc"}), ("/api/chat/settings", {"key": A + "101", "mode": "bidule", "max_per_hour": -4}),
    ("/api/draft", {"id": 1, "action": "send"}), ("/api/draft", {"id": 2, "action": "discard"}), ("/api/draft", {"id": 999}), ("/api/draft", {}),
    ("/api/send", {"key": A + "101", "text": "salut"}), ("/api/send", {"key": A + "101", "text": "  "}), ("/api/send", {"key": "nope", "text": "x"}), ("/api/send", {}),
    ("/api/chat/import", {"key": A + "101", "pages": 3}), ("/api/chat/import", {"key": "nope"}),
    ("/api/chat/add", {"id": 555, "account": "demo", "name": "Nouveau"}), ("/api/chat/add", {"id": "abc"}), ("/api/chat/add", {"id": -5}),
    ("/api/chat/add", {"id": 556, "e2ee": True}), ("/api/chat/add", {"id": 557, "account": "nope"}),
    ("/api/history/enroll", {"pin": "123456"}), ("/api/history/enroll", {"pin": "123456", "confirm": True}), ("/api/history/enroll", {"pin": "12", "confirm": True}),
    ("/api/chat/prepare", {"key": A + "101"}), ("/api/chat/prepare", {"key": "nope"}), ("/api/chat/prepare/discard", {"key": A + "101"}),
    ("/api/message/edit", {"key": A + "101", "id": "mA", "text": "modifié"}), ("/api/message/edit", {"key": A + "101", "id": "mA", "revert": True}),
    ("/api/message/edit", {"key": A + "101"}), ("/api/message/edit", {"key": "nope", "id": "x", "text": "y"}),
    ("/api/chat/memory/refresh", {"key": A + "101"}), ("/api/chat/sync", {"key": A + "101"}), ("/api/chat/sync", {"key": "nope"}), ("/api/sync/all", {}),
    ("/api/chat/raise_limit", {"key": A + "103"}), ("/api/chat/raise_limit", {"key": "nope"}), ("/api/chat/unmute", {"key": A + "101"}), ("/api/chat/unmute", {"key": "nope"}),
    ("/api/chat/preview", {"key": A + "101"}), ("/api/chat/send_preview", {"key": A + "101", "text": "hey"}), ("/api/chat/send_preview", {"key": A + "101", "text": ""}),
    ("/api/chat/force", {"key": A + "101", "send": False}), ("/api/chat/force", {"key": A + "101", "send": True, "hint": "indice"}), ("/api/chat/force", {"key": "nope"}),
    ("/api/chat/pin", {"key": A + "101", "pinned": True}), ("/api/chat/pin", {"key": A + "101"}), ("/api/chat/pin", {"key": "nope"}),
    ("/api/chat/rename", {"key": A + "101", "name": "Zed"}), ("/api/chat/rename", {"key": "nope", "name": "x"}),
    ("/api/chat/delete", {"key": A + "106"}), ("/api/chat/delete", {"key": A + "106", "confirm": True}), ("/api/chat/delete", {"key": "nope", "confirm": True}),
    ("/api/names/resolve", {}), ("/api/threads/load", {}), ("/api/style/analyze", {"account": "demo"}), ("/api/style/analyze", {"account": "nope"}),
    ("/api/style/learn", {"account": "demo"}), ("/api/style/learn", {}),
    ("/api/clear_attention", {"key": A + "103"}), ("/api/clear_attention", {"key": "nope"}),
    ("/api/accounts/ext_code", {}), ("/api/accounts/login/start", {"h": 700, "w": 900}), ("/api/accounts/login/input", {}), ("/api/accounts/login/cancel", {}),
    ("/api/accounts/import_curl", {"curl": "curl 'https://www.messenger.com' -H 'cookie: c_user=100077; xs=aa%3Abb; datr=cc'"}), ("/api/accounts/import_curl", {"curl": "rien"}), ("/api/accounts/import_curl", {}),
    ("/api/accounts/register_e2ee", {"name": "demo"}), ("/api/accounts/register_e2ee", {"name": "demo", "confirm": True}), ("/api/accounts/register_e2ee", {"name": "nope", "confirm": True}),
    ("/api/accounts/remove", {"name": "nope"}), ("/api/accounts/remove", {"name": "nope", "confirm": True}),
    ("/api/nope", {}), ("/api/chat", {}), ("/api/settings", "pas un objet"), ("/api/send", [1, 2]),
]

TS = re.compile(r"^\d{12,}$"); HEX = re.compile(r"^[0-9a-f]{20,}$|^[A-Za-z0-9_-]{30,}$")
def norm(v):
    if isinstance(v, dict): return {k: norm(x) for k, x in sorted(v.items()) if k not in ("log", "tasks", "last_ts", "ts", "created", "started", "ended", "exp", "dur")}
    if isinstance(v, list): return [norm(x) for x in v]
    if isinstance(v, bool) or v is None: return v
    if isinstance(v, int) and v > 10**11: return "<ts>"
    if isinstance(v, str):
        if TS.match(v): return "<ts>"
        if HEX.match(v): return "<id>"
        return re.sub(r"\d{2}:\d{2}:\d{2}", "<hms>", v)
    return v

def seed(hub):
    now = int(time.time() * 1000)
    hub.add_chat("demo", 101, "Alpha", memory="- [identité|confirmé] Alex", instructions="ami")
    hub.add_chat("demo", 102, "Beta", mode="draft"); hub.add_chat("demo", 103, "Gamma", enabled=0)
    hub.add_chat("demo", 104, "Groupe", enabled=0, is_group=1); hub.add_chat("demo", 106, "Supprimable", enabled=0)
    hub.run_sql("UPDATE chats SET attention=1, attention_note='note' WHERE key='demo:103'")
    for i, (src, t) in enumerate([("contact", "salut"), ("owner", "hey"), ("llm", "ça marche")]):
        hub.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES(?,?,?,?,?,?)", (f"m{'ABC'[i]}", "demo:101", now - 600_000 + i * 1000, "101" if src == "contact" else "me", t, src))
    for i in (1, 2):
        hub.run_sql("INSERT INTO drafts(id,chat_key,text,created,status) VALUES(?,?,?,?,'pending')", (i, "demo:102", f"brouillon {i}", now))

def snapshot(hub):
    return norm({
        "chats": hub.sql("SELECT key,name,enabled,mode,instructions,memory,max_per_hour,delay_s,trusted,pinned,takeover_off,attention,attention_note,is_group,route,jid FROM chats ORDER BY key"),
        "messages": hub.sql("SELECT chat_key,src,text,auto,edited,deleted,local_edit FROM messages ORDER BY chat_key,text,src"),
        "drafts": hub.sql("SELECT id,chat_key,text,status FROM drafts ORDER BY id"),
        "settings": hub.sql("SELECT k,v FROM settings ORDER BY k"), "account_settings": hub.sql("SELECT account,k,v FROM account_settings ORDER BY account,k"),
        "events": hub.sql("SELECT chat_key,kind FROM security_events ORDER BY id"),
    })

def run(root):
    hub = TestHub(accounts={"demo": None}, hub_py=Path(root) / "hub" / "hub.py").start()
    try:
        hub.fast_replies(); seed(hub); h = hub.admin(); out = []
        for path, body in SCENARIO:
            t0 = time.time()
            try:
                st, _, raw, js = h.req("POST", path, body, timeout=4)
            except Exception as e:                                          # blocage / coupure : devient un résultat comparable
                st, raw, js = "ERREUR " + type(e).__name__, b"", None
            if VERBOSE: print(f"   {time.time() - t0:5.1f}s  {st}  {path}", flush=True)
            time.sleep(0.45)
            ops = [norm(o) for o in hub.ops("demo")]
            out.append({"req": f"POST {path} {json.dumps(body, ensure_ascii=False, sort_keys=True)}", "status": st,
                        "json": norm(js) if js is not None else raw[:200].decode("utf-8", "replace"), "db": snapshot(hub), "ops": ops})
        return out
    finally:
        hub.stop()

if __name__ == "__main__":
    old, new = [a for a in sys.argv[1:] if not a.startswith('-')][:2]
    print(f"{len(SCENARIO)} requêtes. Exécution : ancien (1/2), ancien (2/2), nouveau…", flush=True)
    a1, a2, b = run(old), run(old), run(new)
    unstable = {i for i, (x, y) in enumerate(zip(a1, a2)) if x != y}
    diffs = [i for i, (x, y) in enumerate(zip(a1, b)) if x != y and i not in unstable]
    print(f"requêtes instables dans l'ANCIENNE version (exclues) : {len(unstable)}")
    for i in sorted(unstable): print("   ~", a1[i]["req"][:110])
    print(f"requêtes comparées : {len(SCENARIO) - len(unstable)} | différences : {len(diffs)}")
    for i in diffs:
        print("\n  ≠", a1[i]["req"][:120])
        for k in ("status", "json", "db", "ops"):
            if a1[i][k] != b[i][k]:
                print(f"     {k}:\n        ancien: {json.dumps(a1[i][k], ensure_ascii=False)[:300]}\n        nouveau: {json.dumps(b[i][k], ensure_ascii=False)[:300]}")
    sys.exit(1 if diffs else 0)
