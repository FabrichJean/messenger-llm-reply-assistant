"""Harnais « boîte noire » : démarre le VRAI hub dans un dossier temporaire et le pilote par HTTP.

Rien ici ne dépend de l'organisation interne du code (hub.py ou paquet relais/) : seulement
  python3 hub/hub.py  +  variables d'environnement  +  l'API HTTP  +  la base SQLite (réglages/données de départ).
"""
import json, os, socket, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HUB = ROOT / "hub" / "hub.py"
FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")
FAKE_CLIENT = Path(__file__).with_name("fake_client.py")
ADMIN_PW = "Adm1n-test-pass-2026"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Http:
    """Petit client HTTP avec cookie de session et en-tête CSRF (X-Hub)."""
    def __init__(self, base):
        self.base, self.cookie = base, ""

    def req(self, method, path, body=None, headers=None, csrf=True, host=None, timeout=20):
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if csrf and method != "GET":
            h["X-Hub"] = "1"
        if self.cookie:
            h["Cookie"] = self.cookie
        if host:
            h["Host"] = host
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                status, hd, raw = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, hd, raw = e.code, e.headers, e.read()
        for sc in hd.get_all("Set-Cookie") or []:
            self.cookie = sc.split(";")[0]
        try:
            js = json.loads(raw)
        except ValueError:
            js = None
        return status, hd, raw, js

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, body=None, **kw): return self.req("POST", path, body if body is not None else {}, **kw)

    def login(self, user, pw):
        st, _, _, js = self.post("/api/login", {"username": user, "password": pw})
        return st, js


class TestHub:
    """Un hub jetable. accounts : {nom_compte: propriétaire (ou None)}."""
    def __init__(self, accounts=None, hub_py=None, env=None):
        self.hub_py = Path(hub_py) if hub_py else HUB          # autre version du hub (test différentiel)
        self.tmp = Path(tempfile.mkdtemp(prefix="relais-test-"))
        self.data = self.tmp / "data"; self.data.mkdir()
        self.port = free_port(); self.base = f"http://127.0.0.1:{self.port}"
        self.accounts = accounts or {}
        cfg = []
        for name, owner in self.accounts.items():
            d = self.data / "acc" / name; d.mkdir(parents=True)
            cfg.append({"name": name, "label": name.capitalize(), "owner": owner, "dir": str(d), "bin": str(FAKE_CLIENT), "args": []})
        (self.data / "accounts.json").write_text(json.dumps(cfg))
        (self.tmp / "home").mkdir()
        self.extra_env = dict(env or {})
        self.proc = None

    def start(self):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp / "home"), "HUB_DATA": str(self.data), "HUB_PORT": str(self.port),
               "HUB_PASSWORD": ADMIN_PW, "HUB_SKIP_CHECK": "1", "HUB_CLIENT_BIN": str(FAKE_CLIENT), "HUB_ACCOUNTS_ROOT": str(self.data / "acc"),
               "CLAUDE_BIN": str(FAKE_CLAUDE), "CLAUDE_FAKE_DIR": str(self.tmp), "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1", **self.extra_env}
        self.log = open(self.tmp / "hub.out", "wb")
        self.proc = subprocess.Popen([sys.executable, str(self.hub_py)], env=env, stdout=self.log, stderr=subprocess.STDOUT, cwd=str(self.tmp))
        end = time.time() + 25
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("le hub s'est arrêté au démarrage :\n" + (self.tmp / "hub.out").read_text()[-1500:])
            try:
                urllib.request.urlopen(self.base + "/healthz", timeout=1).read(); return self
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("le hub n'a pas démarré")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(8)
            except subprocess.TimeoutExpired: self.proc.kill()
        self.log.close()

    # ---- accès aux données (réglages et chats de départ : le schéma SQL ne change pas pendant la refonte)
    def db(self):
        c = sqlite3.connect(self.data / "hub.db", timeout=10); c.row_factory = sqlite3.Row; return c

    def sql(self, q, args=()):
        with self.db() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def run_sql(self, q, args=()):
        c = self.db()
        try:
            c.execute(q, args); c.commit()
        finally:
            c.close()

    def setting(self, k, v, account=None):
        if account:
            self.run_sql("INSERT INTO account_settings(account,k,v) VALUES(?,?,?) ON CONFLICT(account,k) DO UPDATE SET v=excluded.v", (account, k, str(v)))
        else:
            self.run_sql("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    def fast_replies(self):
        for k, v in (("read_delay", "0"), ("typing", "0"), ("takeover_min", "0"), ("judge", "0")):
            self.setting(k, v)

    def add_chat(self, account, thread, name, enabled=1, mode="auto", memory="", instructions="", owner_msgs=10, is_group=0):
        key = f"{account}:{thread}"
        now = int(time.time() * 1000)
        self.run_sql("INSERT INTO chats(key,account,name,last_ts,last_text,thread,is_group,enabled,enabled_at,mode,instructions,memory,max_per_hour,delay_s) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (key, account, name, now - 5000, "", thread, is_group, enabled, now - 86_400_000, mode, instructions, memory, 50, 0))
        for i, t in enumerate(["ok", "oui", "haha", "d'accord", "non", "ça marche", "ok ok", "bof", "salut", "oui oui", "ça roule", "top"][:owner_msgs]):
            self.run_sql("INSERT INTO messages(id,chat_key,ts,sender,text,src) VALUES(?,?,?,?,?,?)", (f"seed{key}{i}", key, now - 90_000_000 + i * 1000, "me", t, "owner"))
        return key

    # ---- faux client et faux claude
    def acct_dir(self, account): return self.data / "acc" / account

    def inject(self, account, thread, text, **extra):
        ev = {"type": "message", "thread": thread, "sender": thread, "text": text, "ts": int(time.time() * 1000), "id": f"in{time.time_ns()}", "from_me": False}
        ev.update(extra)
        with open(self.acct_dir(account) / "events.in", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def ops(self, account):
        p = self.acct_dir(account) / "ops.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def sent_texts(self, account):
        return [o["text"] for o in self.ops(account) if "text" in o]

    def wait(self, cond, timeout=15, step=0.2):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v: return v
            time.sleep(step)
        return None

    def claude_rules(self, rules):
        (self.tmp / "claude_rules.json").write_text(json.dumps(rules, ensure_ascii=False))

    def claude_calls(self):
        p = self.tmp / "claude_calls.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []

    def admin(self):
        h = Http(self.base); st, _ = h.login("admin", ADMIN_PW); assert st == 200, st; return h


def raw_http(port, data, timeout=6, read=65536):
    """Envoie des octets bruts au hub (requêtes malformées) -> (réponse en octets ou None si rien reçu avant le délai, durée)."""
    import time as _t
    t0 = _t.time()
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        reset = False
        try:
            s.sendall(data)
        except (ConnectionResetError, BrokenPipeError):
            reset = True                         # le hub a refusé d'emblée et coupé pendant l'envoi : réponse valable pour un corps trop grand
        s.settimeout(timeout)
        try:
            out = s.recv(read)
        except (ConnectionResetError, BrokenPipeError):
            out = b"RESET"
        except (socket.timeout, TimeoutError):
            out = None
        if reset and not out:
            out = b"RESET"
    return out, _t.time() - t0
