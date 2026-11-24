"""Authentification multi-utilisateurs du hub.

- Chaque utilisateur a un identifiant et un mot de passe (haché avec scrypt + sel aléatoire, fichier users.json en 0600).
- Rôles : « admin » (gère les utilisateurs) et « user ». Un admin ne lit PAS les conversations des autres : l'isolation est la même pour tous.
- Sessions : jetons aléatoires de 256 bits ; seule leur empreinte SHA-256 est gardée (fichier 0600), liée à l'utilisateur et à la version de son mot de passe
  (changer ou réinitialiser un mot de passe, supprimer un utilisateur : ses sessions meurent aussitôt).
- Essais limités par adresse (5 échecs / 5 min) et globalement ; un petit délai à chaque échec ; le temps de réponse ne révèle pas si l'identifiant existe.
- Invitations : lien à usage unique (192 bits aléatoires, seule l'empreinte est gardée, expire après 48 h) ; la personne choisit elle-même son identifiant et son mot de passe.
- Premier démarrage : si aucun utilisateur n'existe et que HUB_PASSWORD est défini, l'administrateur (HUB_ADMIN_USER, « admin » par défaut) est créé avec ce mot de passe.
  Ensuite HUB_PASSWORD n'est plus utilisé : les mots de passe se changent dans l'interface.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

SESSION_TTL = 7 * 86400
MAX_SESSIONS_PER_USER = 20
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")
MIN_PW = 12
MAX_PW = 256
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def _hash(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def check_password_policy(pw):
    if not isinstance(pw, str) or len(pw) < MIN_PW:
        return f"le mot de passe doit faire au moins {MIN_PW} caractères"
    if len(pw) > MAX_PW:
        return "mot de passe trop long"
    if len(set(pw)) < 5:
        return "mot de passe trop répétitif"
    return ""


class Auth:
    def __init__(self, data_dir, bootstrap_password="", admin_name="admin"):
        self._users_path = os.path.join(str(data_dir), "users.json")
        self._sess_path = os.path.join(str(data_dir), "sessions.json")
        self._inv_path = os.path.join(str(data_dir), "invites.json")
        self._invites = {}       # empreinte -> {"by", "exp", "created"}
        self._lock = threading.RLock()
        self._users = {}
        self._sessions = {}      # empreinte -> {"u": nom, "v": version du mot de passe, "exp": expiration}
        self._fails = {}         # ip -> [horodatages d'échecs]
        self._all_fails = []
        self._dummy_salt = secrets.token_bytes(16)
        self._dummy_hash = _hash("dummy-password-for-timing", self._dummy_salt)
        self._load()
        if not self._users and bootstrap_password:
            admin_name = (admin_name or "admin").strip().lower()
            if not NAME_RE.match(admin_name):
                raise SystemExit("HUB_ADMIN_USER invalide (2 à 32 caractères : minuscules, chiffres, . _ -)")
            err = check_password_policy(bootstrap_password)
            if err:
                raise SystemExit("REFUS DE DÉMARRER : HUB_PASSWORD invalide : " + err)
            self._add_user(admin_name, bootstrap_password, "admin")
            self._save_users()
        self.enabled = bool(self._users)

    # ---- persistance
    @staticmethod
    def _read(path):
        try:
            with open(path) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _write(path, data):
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def _load(self):
        d = self._read(self._users_path)
        users = d.get("users") if isinstance(d.get("users"), dict) else {}
        self._users = {k: v for k, v in users.items() if isinstance(v, dict) and NAME_RE.match(k)
                       and all(x in v for x in ("salt", "hash", "role", "pwv"))}
        inv = self._read(self._inv_path).get("i")
        now0 = time.time()
        self._invites = {h: v for h, v in (inv.items() if isinstance(inv, dict) else []) if isinstance(v, dict) and v.get("exp", 0) > now0}
        s = self._read(self._sess_path).get("s")
        now = time.time()
        self._sessions = {}
        if isinstance(s, dict):
            for h, v in s.items():
                u = self._users.get(v.get("u")) if isinstance(v, dict) else None
                if u and v.get("exp", 0) > now and v.get("v") == u["pwv"]:
                    self._sessions[h] = v

    def _save_users(self):
        try:
            self._write(self._users_path, {"users": self._users})
        except OSError:
            pass

    def _save_invites(self):
        try:
            self._write(self._inv_path, {"i": self._invites})
        except OSError:
            pass

    def _save_sessions(self):
        try:
            self._write(self._sess_path, {"s": self._sessions})
        except OSError:
            pass

    # ---- utilisateurs
    def _add_user(self, name, password, role):
        salt = secrets.token_bytes(16)
        self._users[name] = {"salt": salt.hex(), "hash": _hash(password, salt).hex(), "role": role, "pwv": secrets.token_hex(8), "created": int(time.time())}

    def list_users(self):
        with self._lock:
            return [{"name": n, "role": u["role"], "created": u.get("created", 0)} for n, u in sorted(self._users.items())]

    def exists(self, name):
        with self._lock:
            return name in self._users

    def admins(self):
        with self._lock:
            return [n for n, u in self._users.items() if u["role"] == "admin"]

    def create_user(self, name, password, role="user"):
        name = str(name or "").strip().lower()
        if not NAME_RE.match(name):
            raise ValueError("identifiant invalide (2 à 32 caractères : minuscules, chiffres, . _ -)")
        if role not in ("user", "admin"):
            raise ValueError("rôle invalide")
        err = check_password_policy(password)
        if err:
            raise ValueError(err)
        with self._lock:
            if name in self._users:
                raise ValueError("cet identifiant existe déjà")
            self._add_user(name, password, role)
            self._save_users()
            self.enabled = True

    def set_password(self, name, password):
        err = check_password_policy(password)
        if err:
            raise ValueError(err)
        with self._lock:
            u = self._users.get(name)
            if not u:
                raise ValueError("utilisateur inconnu")
            salt = secrets.token_bytes(16)
            u.update(salt=salt.hex(), hash=_hash(password, salt).hex(), pwv=secrets.token_hex(8))
            self._drop_sessions(name)
            self._save_users()

    def change_password(self, name, old, new):
        with self._lock:
            u = self._users.get(name)
            if not u or not hmac.compare_digest(_hash(str(old or ""), bytes.fromhex(u["salt"])).hex(), u["hash"]):
                raise ValueError("mot de passe actuel incorrect")
        self.set_password(name, new)

    def delete_user(self, name):
        with self._lock:
            u = self._users.get(name)
            if not u:
                raise ValueError("utilisateur inconnu")
            if u["role"] == "admin" and len(self.admins()) <= 1:
                raise ValueError("impossible de supprimer le dernier administrateur")
            del self._users[name]
            self._drop_sessions(name)
            self._save_users()

    def _drop_sessions(self, name):
        self._sessions = {h: v for h, v in self._sessions.items() if v.get("u") != name}
        self._save_sessions()

    # ---- invitations
    INVITE_TTL = 48 * 3600

    def create_invite(self, by):
        """-> (jeton, expiration). Le jeton n'est jamais conservé : seule son empreinte."""
        with self._lock:
            now = time.time()
            self._invites = {h: v for h, v in self._invites.items() if v["exp"] > now}
            if len(self._invites) >= 50:
                raise ValueError("trop d'invitations en attente : révoque-en quelques-unes")
            tok = secrets.token_urlsafe(24)
            self._invites[hashlib.sha256(tok.encode()).hexdigest()] = {"by": by, "exp": now + self.INVITE_TTL, "created": int(now)}
            self._save_invites()
            return tok, int(now + self.INVITE_TTL)

    def list_invites(self):
        with self._lock:
            now = time.time()
            return [{"id": h[:10], "by": v["by"], "exp": int(v["exp"]), "created": v.get("created", 0)}
                    for h, v in sorted(self._invites.items(), key=lambda kv: kv[1]["exp"]) if v["exp"] > now]

    def revoke_invite(self, inv_id):
        if not isinstance(inv_id, str) or len(inv_id) < 8:
            raise ValueError("invitation inconnue")
        with self._lock:
            hs = [h for h in self._invites if h.startswith(inv_id)]
            if len(hs) != 1:
                raise ValueError("invitation inconnue")
            del self._invites[hs[0]]
            self._save_invites()

    def redeem_invite(self, token, name, password, ip):
        """Crée l'utilisateur si le lien est valide, puis le brûle. Lève PermissionError (trop d'essais) ou ValueError (lien/identifiant/mot de passe)."""
        if self.locked(ip):
            raise PermissionError("trop d'essais : réessaie dans quelques minutes")
        h = hashlib.sha256(str(token or "")[:200].encode()).hexdigest()
        with self._lock:
            inv = self._invites.get(h)
            ok = bool(inv and inv["exp"] > time.time())
            if ok:
                self.create_user(name, password, "user")   # ValueError si identifiant pris / mot de passe faible : le lien reste valable
                del self._invites[h]
                self._save_invites()
                self._fails.pop(ip, None)
        if not ok:
            with self._lock:
                self._fails.setdefault(ip, []).append(time.time())
                self._all_fails.append(time.time())
            time.sleep(0.6)
            raise ValueError("lien d'invitation invalide ou expiré")

    # ---- limitation des essais
    def locked(self, ip):
        now = time.time()
        with self._lock:
            fl = [t for t in self._fails.get(ip, []) if now - t < 300]
            if fl:
                self._fails[ip] = fl
            else:
                self._fails.pop(ip, None)      # pas d'entrée résiduelle : une rotation d'adresses ne doit pas faire grossir la mémoire sans limite
            if len(self._fails) > 5000:       # garde-fou absolu : on oublie les plus anciennes adresses
                for k in sorted(self._fails, key=lambda a: self._fails[a][-1])[:len(self._fails) - 5000]:
                    del self._fails[k]
            self._all_fails = [t for t in self._all_fails if now - t < 600]
            return len(fl) >= 5 or len(self._all_fails) >= 30

    # ---- connexion
    def login(self, username, password, ip):
        """-> jeton de session, ou None. Lève PermissionError si l'adresse est temporairement bloquée."""
        if self.locked(ip):
            raise PermissionError("trop d'essais : réessaie dans quelques minutes")
        name = str(username or "").strip().lower()
        pw = password if isinstance(password, str) and len(password) <= MAX_PW else ""
        with self._lock:
            u = self._users.get(name) if NAME_RE.match(name) else None
            salt = bytes.fromhex(u["salt"]) if u else self._dummy_salt
            want = u["hash"] if u else self._dummy_hash.hex()
        got = _hash(pw, salt).hex()           # même coût que l'identifiant existe ou non
        ok = hmac.compare_digest(got, want) and u is not None
        if not ok:
            with self._lock:
                self._fails.setdefault(ip, []).append(time.time())
                self._all_fails.append(time.time())
            time.sleep(0.6)
            return None
        tok = secrets.token_urlsafe(32)
        with self._lock:
            u = self._users.get(name)
            if not u:
                return None
            now = time.time()
            self._sessions = {h: v for h, v in self._sessions.items() if v["exp"] > now}
            mine = sorted((v["exp"], h) for h, v in self._sessions.items() if v["u"] == name)
            for _, h in mine[:max(0, len(mine) - MAX_SESSIONS_PER_USER + 1)]:
                del self._sessions[h]
            self._sessions[hashlib.sha256(tok.encode()).hexdigest()] = {"u": name, "v": u["pwv"], "exp": now + SESSION_TTL}
            self._fails.pop(ip, None)
            self._save_sessions()
        return tok

    def valid(self, tok):
        """-> {"name", "role"} de l'utilisateur de cette session, sinon None."""
        if not tok or not isinstance(tok, str) or len(tok) > 200:
            return None
        h = hashlib.sha256(tok.encode()).hexdigest()
        with self._lock:
            s = self._sessions.get(h)
            if not s or s["exp"] <= time.time():
                return None
            u = self._users.get(s["u"])
            if not u or u["pwv"] != s["v"]:
                return None
            return {"name": s["u"], "role": u["role"]}

    def logout(self, tok):
        if not tok:
            return
        with self._lock:
            self._sessions.pop(hashlib.sha256(tok.encode()).hexdigest(), None)
            self._save_sessions()
