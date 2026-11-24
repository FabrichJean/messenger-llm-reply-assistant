"""Connexion d'un compte depuis le navigateur du client (extension, navigateur distant)."""

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

from .accounts import connect_account, parse_curl_cookies
from .config import ACCOUNTS_ROOT, EXT_DIR, LOGIN_ENV_KEEP, LOGIN_KEYS, LOGIN_PY, LOGIN_SCRIPT, REMOTE_LOGIN
from .context import log
from .db import L, NOW


LOGIN = {}   # nom -> {"proc","state","error","user_id","started"}


EXT_CODES = {}     # empreinte du code -> {"owner", "exp"}


EXT_FAILS = {}     # adresse -> [horodatages d'échecs]


def ext_new_code(owner):
    now = time.time()
    with L:
        for h in [h for h, v in EXT_CODES.items() if v["exp"] < now]:
            del EXT_CODES[h]
        if sum(1 for v in EXT_CODES.values() if v["owner"] == owner) >= 5:
            raise ValueError("trop de connexions en attente : réessaie dans quelques minutes")
        code = secrets.token_urlsafe(24)
        EXT_CODES[hashlib.sha256(code.encode()).hexdigest()] = {"owner": owner, "exp": now + 600}
    return code


def ext_import(code, cookies, ip):
    """Appelé par l'extension (sans session du hub) : le code à usage unique, émis pour un utilisateur connecté, prouve à qui rattacher le compte."""
    now = time.time()
    with L:
        fl = [t for t in EXT_FAILS.get(ip, []) if now - t < 600]
        EXT_FAILS[ip] = fl
        if len(fl) >= 10:
            return {"error": "trop d'essais : réessaie dans quelques minutes"}
    h = hashlib.sha256(str(code or "")[:200].encode()).hexdigest()
    with L:
        ent = EXT_CODES.pop(h, None)   # pris de façon atomique : deux requêtes simultanées ne peuvent pas l'utiliser toutes les deux
    if not ent or ent["exp"] < now:
        with L:
            EXT_FAILS.setdefault(ip, []).append(now)
        time.sleep(0.5)
        return {"error": "code expiré : relance la connexion depuis le hub"}
    jar = parse_curl_cookies(str(cookies or "")[:8000])
    try:
        if not jar:
            raise ValueError("session Messenger introuvable dans ce navigateur")
        name, reused = connect_account(jar, ent["owner"])
    except ValueError as ex:
        with L:
            EXT_CODES[h] = ent   # échec (session refusée, etc.) : le code reste valable pour une nouvelle tentative
        return {"error": str(ex)}
    return {"ok": True, "name": name, "reused": reused}


def ext_zip(origin):
    """Extension prête à installer, configurée pour CE hub (adresse du hub incluse)."""
    import io
    import zipfile
    login_url = os.environ.get("HUB_EXT_LOGIN_URL", "https://www.messenger.com/")
    cookie_url = os.environ.get("HUB_EXT_COOKIE_URL", "https://www.messenger.com")
    cu = urlparse(cookie_url)
    cookie_host = "https://*.messenger.com/*" if (cu.hostname or "").endswith("messenger.com") else f"{cu.scheme}://{cu.hostname}/*"
    manifest = (EXT_DIR / "manifest.template.json").read_text().replace("__COOKIE_HOST__", cookie_host).replace("__HUB_ORIGIN__", origin)
    cfg = "const CFG = " + json.dumps({"hub": origin, "loginUrl": login_url, "cookieUrl": cookie_url}) + ";\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("relais-connect/manifest.json", manifest)
        z.writestr("relais-connect/config.js", cfg)
        for f in ("background.js", "content.js", "README.txt"):
            z.write(EXT_DIR / f, "relais-connect/" + f)
    return buf.getvalue()


def _lkey(owner=None):
    return owner or "local"


def start_login(owner=None, size=None):
    key = _lkey(owner)
    prev = LOGIN.get(key)
    if prev and prev["state"] in ("starting", "waiting_login", "captured"):
        return {"error": "une connexion est déjà ouverte : termine-la ou annule-la d'abord"}
    if REMOTE_LOGIN and sum(1 for v in LOGIN.values() if v["state"] in ("starting", "waiting_login", "captured")) >= 2:
        return {"error": "le serveur est occupé par d'autres connexions : réessaie dans une minute"}
    if not LOGIN_PY.exists() or not LOGIN_SCRIPT.exists():
        return {"error": "outil de connexion non installé"}
    d = ACCOUNTS_ROOT / ".login" / re.sub(r"[^a-z0-9_.-]", "_", key)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    # profil et cookies dans un dossier TEMPORAIRE : aucun compte existant n'est touché tant que la connexion n'a pas réussi
    cmd = [str(LOGIN_PY), str(LOGIN_SCRIPT), "--out", str(d / "cookies.json.new"), "--profile", str(d / ".browser")]
    w = h = 0
    if REMOTE_LOGIN:
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            w, h = 420, 600
        w, h = max(280, min(w, 900)), max(320, min(h, 1200))
        cmd += ["--remote", "--size", f"{w}x{h}", "--frame", str(d / "frame.jpg")]
    if os.environ.get("HUB_LOGIN_URL"):
        cmd += ["--url", os.environ["HUB_LOGIN_URL"]]
    if os.environ.get("HUB_LOGIN_DOMAINS"):
        cmd += ["--domains", os.environ["HUB_LOGIN_DOMAINS"]]
    if os.environ.get("HUB_LOGIN_HEADLESS") == "1":
        cmd += ["--headless"]
    info = {"state": "starting", "error": "", "user_id": "", "name": "", "reused": False, "started": NOW(), "proc": None, "owner": owner, "phase": "",
            "dir": d, "remote": REMOTE_LOGIN, "size": (w, h), "wlock": threading.Lock()}
    LOGIN[key] = info
    try:
        env = {k: v for k, v in os.environ.items() if k in LOGIN_ENV_KEEP}   # le navigateur ne voit ni le mot de passe du hub ni les clés
        info["proc"] = subprocess.Popen(cmd, stdin=subprocess.PIPE if REMOTE_LOGIN else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
    except Exception as ex:
        info.update(state="error", error=str(ex)[:150])
        return {"error": info["error"]}
    threading.Thread(target=_watch_login, args=(info,), daemon=True).start()
    log("info", "Fenêtre de connexion ouverte" + (" (navigateur distant)" if REMOTE_LOGIN else ""), acct=None)
    return {"ok": True, "remote": REMOTE_LOGIN, "size": [w, h]}


def login_input(owner, b):
    """Commande de l'utilisateur vers son navigateur distant (clic, texte, touche, défilement) : validée avant d'être transmise."""
    info = LOGIN.get(_lkey(owner))
    if not info or not info.get("remote") or info["state"] not in ("starting", "waiting_login"):
        return {"error": "aucune connexion en cours"}
    t = b.get("t")
    if t not in LOGIN_KEYS:
        return {"error": "commande inconnue"}
    w, h = info["size"]
    if t == "click":
        cmd = {"t": "click", "x": max(0.0, min(float(b["x"]), w)), "y": max(0.0, min(float(b["y"]), h))}
    elif t == "text":
        cmd = {"t": "text", "s": "".join(ch for ch in str(b.get("s", ""))[:200] if ch.isprintable())}
    elif t == "login":
        em, pw = b.get("email"), b.get("password")
        if not isinstance(em, str) or not isinstance(pw, str) or not (1 <= len(em) <= 200) or not (1 <= len(pw) <= 256) or "\n" in em or "\r" in em:
            return {"error": "identifiant ou mot de passe invalide"}
        cmd = {"t": "login", "email": em, "pass": pw}
        info["phase"] = "submitted"
    elif t == "key":
        if b.get("k") not in ("Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
            return {"error": "touche non autorisée"}
        cmd = {"t": "key", "k": b["k"]}
    else:
        cmd = {"t": "scroll", "dy": max(-1500.0, min(float(b.get("dy", 0)), 1500.0))}
    try:
        with info["wlock"]:
            info["proc"].stdin.write(json.dumps(cmd) + "\n")   # jamais journalisé : un texte saisi peut être un mot de passe
            info["proc"].stdin.flush()
    except (OSError, ValueError, AttributeError):
        return {"error": "la fenêtre de connexion est fermée"}
    return {"ok": True}


def _watch_login(info):
    d = info["dir"]
    for line in info["proc"].stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("phase") in ("submitted", "badcreds", "challenge"):
            info["phase"] = ev["phase"]
        if ev.get("state") == "waiting_login":
            info["state"] = "waiting_login"
        elif ev.get("state") == "captured":
            info.update(state="captured", user_id=str(ev.get("user_id") or ""))
        elif ev.get("state") == "error":
            info.update(state="error", error=str(ev.get("error"))[:200])
    info["proc"].wait()
    if info["state"] == "captured":
        try:
            jar = json.loads((d / "cookies.json.new").read_text())
            info["name"], info["reused"] = connect_account(jar, info.get("owner"))
            info["state"] = "done"
        except Exception as ex:
            info.update(state="error", error=str(ex)[:200] if isinstance(ex, ValueError) else f"ajout du compte impossible : {ex}"[:200])
    elif info["state"] in ("starting", "waiting_login"):
        info.update(state="error", error=info["error"] or "connexion interrompue")
    for _ in range(8):   # profil du navigateur + fichier temporaire : la session n'est gardée que dans le dossier du compte (Chrome peut finir d'écrire après l'arrêt)
        shutil.rmtree(d, ignore_errors=True)
        if not d.exists():
            break
        time.sleep(1)
    if info["state"] == "error":
        log("warn", f"Connexion non terminée : {info['error']}")
    elif info["state"] == "done":
        log("info", f"Compte « {info['name']} » {'reconnecté' if info['reused'] else 'ajouté'}")
