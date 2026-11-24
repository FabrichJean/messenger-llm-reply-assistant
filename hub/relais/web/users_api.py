"""Gestion des utilisateurs, invitations et mots de passe (administrateur)."""

from ..accounts import ACCOUNTS, save_accounts
from ..context import AUTH, acct_of, clean, cur, is_admin, log
from ..llm.timers import cancel_timer, timers


def users_api(path, b):
    me = cur()
    if not isinstance(b, dict):
        return {"error": "requête invalide"}
    if path == "/api/me/password":
        if not AUTH.enabled or not me:
            return {"error": "l'authentification n'est pas activée"}
        try:
            AUTH.change_password(me["name"], b.get("old"), b.get("new"))
        except ValueError as ex:
            return {"error": str(ex)}
        log("info", f"Mot de passe modifié par « {clean(me['name'])} » (toutes ses sessions sont fermées)")
        return {"ok": True}
    if not AUTH.enabled or not is_admin():
        return {"error": "réservé à l'administrateur"}
    if path == "/api/users/invite":
        try:
            tok, exp = AUTH.create_invite(me["name"])
        except ValueError as ex:
            return {"error": str(ex)}
        log("info", f"Invitation créée par « {clean(me['name'])} » (valable 48 h, usage unique)")
        return {"ok": True, "path": "/join#" + tok, "exp": exp}
    if path == "/api/users/invite_revoke":
        try:
            AUTH.revoke_invite(b.get("id"))
        except ValueError as ex:
            return {"error": str(ex)}
        return {"ok": True}
    if path == "/api/users/list":
        owned = {}
        for a in ACCOUNTS.values():
            owned.setdefault(a.owner, []).append(a.label or a.name)
        return {"users": [{**u, "accounts": owned.get(u["name"], [])} for u in AUTH.list_users()], "invites": AUTH.list_invites(),
                "unowned": [a.label or a.name for a in ACCOUNTS.values() if not a.owner or not AUTH.exists(a.owner)]}
    try:
        if path == "/api/users/create":
            AUTH.create_user(b.get("name"), b.get("password"), "admin" if b.get("role") == "admin" else "user")
            log("info", f"Utilisateur « {clean(b.get('name'))} » créé par « {clean(me['name'])} »")
            return {"ok": True}
        name = b.get("name")
        if not isinstance(name, str) or not AUTH.exists(name):
            return {"error": "utilisateur inconnu"}
        if path == "/api/users/reset":
            AUTH.set_password(name, b.get("password"))
            log("info", f"Mot de passe de « {clean(name)} » réinitialisé par « {clean(me['name'])} »")
            return {"ok": True}
        if path == "/api/users/delete":
            if name == me["name"]:
                return {"error": "tu ne peux pas supprimer ton propre compte"}
            owned = [a.name for a in ACCOUNTS.values() if a.owner == name]
            if owned and not b.get("remove_accounts"):
                return {"error": f"cet utilisateur possède {len(owned)} compte(s) Messenger : confirme leur retrait du hub (les fichiers sont conservés sur le disque)"}
            if not b.get("confirm"):
                return {"error": "confirmation requise"}
            AUTH.delete_user(name)
            for n in owned:
                for k in [k for k in timers if acct_of(k) == n]:
                    cancel_timer(k)
                ACCOUNTS[n].shutdown()
                del ACCOUNTS[n]
            if owned:
                save_accounts()
            log("info", f"Utilisateur « {clean(name)} » supprimé par « {clean(me['name'])} » ({len(owned)} compte(s) retiré(s) du hub)")
            return {"ok": True}
        if path == "/api/users/assign":
            acct = ACCOUNTS.get(b.get("account"))
            if not acct:
                return {"error": "compte inconnu"}
            acct.owner = name
            save_accounts()
            log("info", f"Compte « {clean(acct.name)} » attribué à « {clean(name)} » par « {clean(me['name'])} »")
            return {"ok": True}
    except ValueError as ex:
        return {"error": str(ex)}
    return {"error": "route inconnue"}
