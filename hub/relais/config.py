"""Configuration : variables d'environnement, chemins, constantes de démarrage."""

import json
import os
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]   # dossier hub/ (ce fichier est dans hub/relais/)


os.umask(0o077)   # tout fichier créé (base, cookies, pièces jointes, sessions) n'est lisible que par ce processus


sys.path.insert(0, str(HERE))


DATA = Path(os.environ.get("HUB_DATA", HERE))


PORT = int(os.environ.get("HUB_PORT", "8787"))


BIND = os.environ.get("HUB_BIND", "127.0.0.1")


ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"} | {h.strip().lower() for h in os.environ.get("HUB_ALLOWED_HOSTS", "").split(",") if h.strip()}


TRUST_PROXY = os.environ.get("HUB_TRUST_PROXY") == "1"        # derrière Caddy / nginx : on lit X-Forwarded-*


SECURE_COOKIE = os.environ.get("HUB_SECURE_COOKIE") == "1"


CLAUDE = os.environ.get("CLAUDE_BIN", "claude")


DATA.mkdir(parents=True, exist_ok=True)


SANDBOX = DATA / "sandbox"


SANDBOX.mkdir(exist_ok=True)


acc_file = DATA / "accounts.json"


ACCOUNT_CFG = json.loads(acc_file.read_text()) if acc_file.exists() else []   # aucun compte par défaut : on les ajoute depuis l'interface


(DATA / "avatars").mkdir(exist_ok=True)


ACCOUNTS_ROOT = Path(os.environ.get("HUB_ACCOUNTS_ROOT", HERE.parent / "accounts"))


def _default_client_bin():
    """Client Go : bin/messenger-lite (go build -o bin/messenger-lite ./cmd/messenger-lite), sinon l'ancien emplacement à la racine."""
    for p in (HERE.parent / "bin" / "messenger-lite", HERE.parent / "messenger-lite"):
        if p.exists():
            return str(p)
    return str(HERE.parent / "bin" / "messenger-lite")


CLIENT_BIN = os.environ.get("HUB_CLIENT_BIN", _default_client_bin())


REMOTE_LOGIN = os.environ.get("HUB_LOGIN_REMOTE") == "1"   # serveur sans écran : navigateur distant affiché dans une fenêtre modale du hub


LOGIN_PY = Path(os.environ.get("HUB_LOGIN_PY") or (HERE.parent / ".venv" / "bin" / "python"))


if REMOTE_LOGIN and not LOGIN_PY.exists():
    LOGIN_PY = Path(sys.executable)


LOGIN_SCRIPT = HERE.parent / "tools" / "login_browser.py"


LOGIN_ENV_KEEP = ("PATH", "HOME", "TZ", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "LOGIN_NO_SANDBOX", "LOGIN_CHANNEL", "LOGIN_TEST_HOST", "DISPLAY", "SSL_CERT_FILE", "SSL_CERT_DIR")


LOGIN_KEYS = ("click", "text", "key", "scroll", "login")


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,19}$")


EXT_DIR = HERE.parent / "extension"


# Journal des champs reçus (jamais le contenu) pour les évènements « debug » du client : HUB_DEBUG=1
HUB_DEBUG = os.environ.get("HUB_DEBUG") == "1"
