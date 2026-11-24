"""Comptes Messenger : processus client (un par compte), propriété, connexion par cookies."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .config import ACCOUNTS_ROOT, ACCOUNT_CFG, CLIENT_BIN, DATA, HERE, NAME_RE
from .context import AUTH, acct_of, cur, log
from .db import q
from .llm.timers import cancel_timer, timers


def default_account():
    """Premier compte s'il y en a (sinon None). Il n'existe pas de compte « principal » : tous les comptes sont égaux."""
    return next(iter(ACCOUNTS), None)


def mine():
    """Noms des comptes Messenger que l'utilisateur courant possède (sans authentification activée : usage local, tous les comptes)."""
    if not AUTH.enabled:
        return set(ACCOUNTS)
    u = cur()
    return {n for n, a in ACCOUNTS.items() if u and a.owner == u["name"]}


def own_chat(key):
    if not isinstance(key, str):
        return False
    r = q("SELECT account FROM chats WHERE key=?", (key,))
    return bool(r) and r[0]["account"] in mine()


class Account:
    def __init__(self, cfg):
        self.name, self.dir, self.bin = cfg["name"], cfg["dir"], cfg["bin"]
        self.owner = cfg.get("owner")               # utilisateur du hub à qui appartient ce compte (isolation multi-utilisateurs)
        self.label = str(cfg.get("label") or "")   # nom d'affichage = vrai nom du profil Messenger (la clé interne `name` ne change jamais)
        self.base_args = list(cfg.get("args", []))
        self.args = list(self.base_args)
        self.proc = None
        self.lock = threading.Lock()
        self.state = {"running": False, "classic": False, "e2ee": False, "note": ""}
        self.stop = False
        self.thread = None
        self.down_since = 0

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name=f"acct-{self.name}")
        self.thread.start()

    def loop(self):
        from .events import handle_event   # import différé : casse le cycle accounts <-> events
        backoff = 3
        while not self.stop:
            t0 = time.time()
            try:
                err = open(DATA / f"{self.name}.err", "wb")
                launch_args = list(self.args)
                if "-register-e2ee" in launch_args:
                    self.args = list(self.base_args)  # l'enregistrement de l'appareil n'est tenté qu'UNE fois, jamais en boucle
                cenv = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TZ", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")}
                self.proc = subprocess.Popen([self.bin, *launch_args], cwd=self.dir, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1, env=cenv)
                self.state.update(running=True, note="")
                log("info", f"[{self.name}] client démarré")
                for line in self.proc.stdout:
                    try:
                        handle_event(self, json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:  # ne jamais tuer la boucle de lecture
                        log("error", f"[{self.name}] événement ignoré: {e!r}")
                self.proc.wait()
            except FileNotFoundError:
                self.state["note"] = f"binaire introuvable: {self.bin}"
            except Exception as e:
                self.state["note"] = repr(e)
            self.state.update(running=False, classic=False, e2ee=False)
            if self.stop:
                break
            try:   # session refusée par Messenger : inutile de réessayer en boucle (ça n'arrange rien et peut alerter Meta)
                tail = (DATA / f"{self.name}.err").read_text(errors="replace")[-600:]
            except OSError:
                tail = ""
            if "user id in initial data is zero" in tail or "access token is no longer valid" in tail:
                self.state.update(expired=True, note="session expirée ou refusée : reconnecte ce compte (👤 Comptes)")
                log("warn", f"[{self.name}] session refusée par Messenger : reconnecte le compte (arrêt des tentatives)")
                break
            if "/privacy/consent" in tail or "/checkpoint" in tail or "two_step_verification" in tail or "/login/?next" in tail:
                # Meta demande une action à la personne (consentement, vérification de sécurité) : inutile de réessayer depuis le serveur, ça n'arrange rien
                self.state.update(expired=True, note="Meta demande une validation (consentement ou vérification de sécurité). Reconnecte ce compte depuis l'application : accepte la demande qui s'affiche, puis le compte repart tout seul.")
                log("warn", f"[{self.name}] Meta demande une validation (consentement ou vérification) : arrêt des tentatives, reconnexion nécessaire")
                break
            self.state["expired"] = False
            backoff = 3 if time.time() - t0 > 60 else min(backoff * 2, 120)
            log("warn", f"[{self.name}] client arrêté, relance dans {backoff}s {self.state['note']}")
            time.sleep(backoff)

    def send(self, cmd):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return False
            try:
                self.proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
                return True
            except Exception:
                return False

    def shutdown(self):
        self.stop = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def _fix_cfg(c):
    """Un accounts.json venu d'une autre machine contient des chemins qui n'existent pas ici : on les recalcule."""
    root, cli = ACCOUNTS_ROOT, CLIENT_BIN
    c = dict(c)
    if not Path(c["dir"]).exists() and (root / c["name"]).exists():
        c["dir"] = str(root / c["name"])
    if not Path(c["bin"]).exists():
        c["bin"] = cli
    return c


ACCOUNTS = {c["name"]: Account(_fix_cfg(c)) for c in ACCOUNT_CFG}


def save_accounts():
    """Liste des comptes sur disque (sans l'indicateur temporaire d'enregistrement)."""
    data = [{"name": a.name, "label": a.label, "owner": a.owner, "dir": a.dir, "bin": a.bin, "args": a.base_args} for a in ACCOUNTS.values()]
    tmp = DATA / "accounts.json.tmp"
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, DATA / "accounts.json")


def add_account(name, dirpath, owner=None):
    cfg = {"name": name, "dir": str(dirpath), "bin": CLIENT_BIN, "args": [], "owner": owner}
    acct = Account(cfg)
    ACCOUNTS[name] = acct
    save_accounts()
    acct.start()
    log("info", f"Compte « {name} » ajouté", acct=name)
    return acct


def _migrate_owners():
    """Tout compte sans propriétaire valide est rattaché à l'utilisateur du même nom, sinon au premier administrateur."""
    if not AUTH.enabled:
        return
    adm = (AUTH.admins() or [None])[0]
    changed = False
    for a in ACCOUNTS.values():
        if not a.owner or not AUTH.exists(a.owner):
            a.owner = a.name if AUTH.exists(a.name) else adm
            changed = True
    if changed:
        save_accounts()


_migrate_owners()


def has_registered_device(dirpath):
    """Vrai seulement si un appareil chiffré est VRAIMENT enregistré (le fichier e2ee.db existe dès le premier démarrage du client, même vide)."""
    f = Path(dirpath) / "e2ee.db"
    if not f.exists():
        return False
    try:
        c = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=2)
        try:
            return c.execute("SELECT COUNT(*) FROM whatsmeow_device").fetchone()[0] > 0
        finally:
            c.close()
    except sqlite3.Error:
        return False


def account_dir(name):
    d = ACCOUNTS_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def parse_curl_cookies(text):
    """Cookies d'une commande « Copy as cURL » (ou d'un en-tête Cookie collé). Les valeurs ne sont jamais affichées."""
    m = re.search(r"""(?:-b|--cookie)\s+(['"])(.*?)\1""", text, re.S) or re.search(r"""-H\s+(['"])\s*cookie:\s*(.*?)\1""", text, re.S | re.I)
    header = m.group(2) if m else text
    jar = {}
    for part in re.split(r";\s*", header.strip()):
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip().strip("'\"")
    keep = ("c_user", "xs", "datr", "sb", "fr", "wd", "presence", "dpr", "oo")
    if not all(jar.get(k) for k in ("c_user", "xs", "datr")):
        return None
    return {k: jar[k] for k in keep if jar.get(k)}


def write_cookies(name, jar):
    d = account_dir(name)
    fd = os.open(d / "cookies.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(jar, f, indent=2)
    return d


def find_account_name(c_user):
    """Nom du dossier déjà associé à ce compte Messenger (même c_user), même si le compte a été retiré de l'application."""
    for a in ACCOUNTS.values():
        try:
            if json.loads((Path(a.dir) / "cookies.json").read_text()).get("c_user") == c_user:
                return a.name
        except (OSError, ValueError):
            pass
    if ACCOUNTS_ROOT.is_dir():
        for d in sorted(ACCOUNTS_ROOT.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            try:
                if json.loads((d / "cookies.json").read_text()).get("c_user") == c_user:
                    return d.name
            except (OSError, ValueError):
                pass
    return None


def new_account_name(c_user):
    """Nom automatique pour un nouveau compte (l'utilisateur n'a rien à saisir)."""
    digits = re.sub(r"\D", "", c_user)
    for n in range(8, len(digits) + 1):
        name = "fb-" + digits[-n:]
        if NAME_RE.match(name) and name not in ACCOUNTS and not (ACCOUNTS_ROOT / name).exists():
            return name
    return "fb-" + digits[-12:]


def check_session(jar):
    """Vérifie, avec le vrai client, que Messenger accepte ces cookies (dossier temporaire : aucun compte n'est touché)."""
    if os.environ.get("HUB_SKIP_CHECK") == "1":
        return
    d = Path(tempfile.mkdtemp(prefix=".check-", dir=str(ACCOUNTS_ROOT) if ACCOUNTS_ROOT.is_dir() else None))
    try:
        os.chmod(d, 0o700)
        fd = os.open(d / "cookies.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(jar, f)
        try:
            r = subprocess.run([CLIENT_BIN, "-check", "-e2ee=false"], cwd=str(d), capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise ValueError("Messenger ne répond pas : réessaie dans un instant")
        except OSError as ex:
            raise ValueError(f"client introuvable : {ex}")
        if r.returncode != 0 or "ok" not in r.stdout:
            err = (r.stderr or "").strip().splitlines()[-1:] or [""]
            log("warn", f"Session refusée par Messenger : {err[0][:200]}")
            if "/privacy/consent" in (r.stderr or "") or "/checkpoint" in (r.stderr or ""):
                raise ValueError("Messenger demande d'abord une validation (écran de consentement ou de sécurité).")
            raise ValueError("Messenger a refusé cette session (connexion pas terminée ?). Recommence en allant jusqu'à ta liste de conversations sur messenger.com.")
    finally:
        shutil.rmtree(d, ignore_errors=True)


CONNECT_LOCK = threading.RLock()


def connect_account(jar, owner=None):
    with CONNECT_LOCK:   # un seul import à la fois : deux requêtes simultanées pour le même compte ne le créent pas deux fois
        return _connect_account(jar, owner)


def _connect_account(jar, owner=None):
    """Enregistre la session. Compte déjà connu (même c_user) : on réutilise son dossier (clés chiffrées, historique) et on remplace seulement les cookies."""
    cu = str(jar.get("c_user") or "")
    if not cu.isdigit():
        raise ValueError("session invalide (identifiant de compte absent)")
    if AUTH.enabled and not owner:
        raise ValueError("utilisateur inconnu")
    name = find_account_name(cu)
    ex = ACCOUNTS.get(name) if name else None
    if AUTH.enabled and ex and ex.owner and ex.owner != owner:
        raise ValueError("ce compte Messenger est déjà relié à un autre utilisateur de ce hub")
    check_session(jar)   # refuse une session que Messenger n'accepte pas, AVANT de toucher aux cookies existants
    reused = bool(name)
    name = name or new_account_name(cu)
    d = account_dir(name)
    tmp = d / "cookies.json.new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(jar, f, indent=2)
    os.replace(tmp, d / "cookies.json")
    old = ACCOUNTS.pop(name, None)
    if old:   # déjà actif : on le redémarre avec la nouvelle session (un seul client par compte)
        for k in [k for k in timers if acct_of(k) == name]:
            cancel_timer(k)
        old.shutdown()
    add_account(name, d, owner)
    return name, reused
