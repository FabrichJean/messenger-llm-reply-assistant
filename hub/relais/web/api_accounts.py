"""Routes des comptes Messenger : connexion, enregistrement de l'appareil chiffré, retrait."""

from ..accounts import ACCOUNTS, connect_account, default_account, has_registered_device, parse_curl_cookies, save_accounts
from ..context import acct_of, cur_name, log
from ..llm.timers import cancel_timer, timers
from ..login import LOGIN, _lkey, ext_new_code, login_input, start_login


def history_enroll(b):
    # POST /api/history/enroll
    pin = str(b.get("pin") or "")
    if not b.get("confirm"):
        return {"error": "confirmation requise"}
    if not (len(pin) == 6 and pin.isdigit()):
        return {"error": "le PIN doit faire exactement 6 chiffres"}
    acct = ACCOUNTS.get(b.get("account") or default_account())
    if not acct or not acct.state.get("e2ee"):
        return {"error": "le canal chiffré n'est pas connecté"}
    acct.state["history"] = "enrolling"
    ok = acct.send({"op": "history_enroll", "pin": pin})
    pin = ""  # le PIN n'est ni stocké ni journalisé
    log("info", "Restauration de l'historique chiffré demandée (PIN transmis au client local, non conservé)")
    return {"ok": ok}


def accounts_ext_code(b):
    # POST /api/accounts/ext_code
    try:
        return {"ok": True, "code": ext_new_code(cur_name())}
    except ValueError as ex:
        return {"error": str(ex)}


def accounts_login_start(b):
    # POST /api/accounts/login/start
    return start_login(cur_name(), (b.get("w"), b.get("h")))


def accounts_login_input(b):
    # POST /api/accounts/login/input
    return login_input(cur_name(), b)


def accounts_login_cancel(b):
    # POST /api/accounts/login/cancel
    info = LOGIN.get(_lkey(cur_name()))
    if info and info["proc"] and info["proc"].poll() is None:
        info["state"] = "cancelled"
        info["proc"].terminate()
    return {"ok": True}


def accounts_import_curl(b):
    # POST /api/accounts/import_curl
    jar = parse_curl_cookies(str(b.get("curl") or ""))
    if not jar:
        return {"error": "cookies introuvables : colle une requête « Copy as cURL » faite sur messenger.com une fois connecté"}
    try:
        name, reused = connect_account(jar, cur_name())
    except ValueError as ex:
        return {"error": str(ex)}
    return {"ok": True, "name": name, "reused": reused}


def accounts_register_e2ee(b):
    # POST /api/accounts/register_e2ee
    acct = ACCOUNTS.get(b.get("name"))
    if not acct:
        return {"error": "compte inconnu"}
    if not b.get("confirm"):
        return {"error": "confirmation requise : cette action ajoute un appareil chiffré sur le compte Messenger"}
    if has_registered_device(acct.dir):
        return {"error": "un appareil chiffré existe déjà pour ce compte : aucun nouvel enregistrement n'est nécessaire"}
    acct.args = ["-register-e2ee"]
    if acct.proc and acct.proc.poll() is None:
        acct.proc.terminate()   # la boucle relance le client avec l'enregistrement (une seule fois)
    log("info", f"[{acct.name}] enregistrement de l'appareil chiffré demandé")
    return {"ok": True}


def accounts_remove(b):
    # POST /api/accounts/remove
    name = b.get("name")
    if name not in ACCOUNTS:
        return {"error": "compte inconnu"}
    if not b.get("confirm"):
        return {"error": "confirmation requise"}
    for k in [k for k in timers if acct_of(k) == name]:
        cancel_timer(k)
    ACCOUNTS[name].shutdown()
    del ACCOUNTS[name]
    save_accounts()
    log("info", f"Compte « {name} » retiré (ses fichiers sont conservés sur le disque)")
    return {"ok": True}


ROUTES = {
    "/api/history/enroll": history_enroll,
    "/api/accounts/ext_code": accounts_ext_code,
    "/api/accounts/login/start": accounts_login_start,
    "/api/accounts/login/input": accounts_login_input,
    "/api/accounts/login/cancel": accounts_login_cancel,
    "/api/accounts/import_curl": accounts_import_curl,
    "/api/accounts/register_e2ee": accounts_register_e2ee,
    "/api/accounts/remove": accounts_remove,
}
