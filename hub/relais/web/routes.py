"""Routes d'écriture de l'API (POST) et contrôle d'accès central."""

from ..accounts import mine, own_chat
from ..context import AUTH, is_admin
from ..db import q
from . import api_accounts, api_chat, api_settings, api_sync
from .users_api import users_api


ROUTES = {**api_settings.ROUTES, **api_chat.ROUTES, **api_accounts.ROUTES, **api_sync.ROUTES}


def _post(path, b):
    """Aiguille une requête POST vers sa fonction. Une route absente (ou dont la fonction ne renvoie rien) répond « route inconnue »."""
    handler = ROUTES.get(path)
    result = handler(b) if handler else None
    return result if result is not None else {"error": "route inconnue"}


KEY_ROUTES = {"/api/send", "/api/chat/import", "/api/chat/prepare", "/api/chat/prepare/discard", "/api/message/edit", "/api/chat/sync", "/api/chat/raise_limit",
              "/api/chat/unmute", "/api/chat/preview", "/api/chat/send_preview", "/api/chat/force", "/api/chat/pin", "/api/chat/delete", "/api/chat/rename",
              "/api/clear_attention", "/api/chat/settings", "/api/chat/memory/refresh"}


ACCT_ROUTES = {"/api/settings/reset": "account", "/api/accounts/register_e2ee": "name", "/api/accounts/remove": "name"}


DEFAULT_ACCT_ROUTES = {"/api/chat/add", "/api/history/enroll", "/api/style/analyze", "/api/style/learn"}


def post(path, b):
    """Point d'entrée des actions : vérifie que l'utilisateur possède bien ce qu'il touche, puis exécute."""
    if path.startswith("/api/users") or path == "/api/me/password":
        return users_api(path, b)
    if AUTH.enabled:
        if not isinstance(b, dict):
            return {"error": "requête invalide"}
        if path in KEY_ROUTES:
            if not own_chat(b.get("key")):
                return {"error": "conversation inconnue"}
        elif path == "/api/draft":
            d = q("SELECT chat_key FROM drafts WHERE id=?", (b.get("id"),))
            if not d or not own_chat(d[0]["chat_key"]):
                return {"error": "brouillon introuvable"}
        elif path in ACCT_ROUTES:
            n = b.get(ACCT_ROUTES[path])
            if not isinstance(n, str) or n not in mine():
                return {"error": "compte inconnu"}
        elif path in DEFAULT_ACCT_ROUTES:
            n = b.get("account") or next(iter(sorted(mine())), None)
            if not isinstance(n, str) or n not in mine():
                return {"error": "compte inconnu"}
            b = dict(b)
            b["account"] = n
        elif path == "/api/settings":
            sc = b.get("account") or None
            if sc:
                if not isinstance(sc, str) or sc not in mine():
                    return {"error": "compte inconnu"}
            elif not is_admin():   # pas de réglages « généraux » pour un utilisateur : on les applique à chacun de SES comptes
                for n in sorted(mine()):
                    _post(path, {**b, "account": n})
                return {"ok": True}
    return _post(path, b)
