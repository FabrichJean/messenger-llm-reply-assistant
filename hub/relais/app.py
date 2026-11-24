"""Démarrage du hub : comptes, synchro de secours, serveur HTTP."""

import sys
import threading

from .accounts import ACCOUNTS
from .config import BIND, PORT
from .context import AUTH, log
from .events import dedupe_owner_echoes
from .sync import autosync_loop
from .web.server import BoundedServer, Handler


def main():
    dedupe_owner_echoes()
    for a in ACCOUNTS.values():
        a.start()
    threading.Thread(target=autosync_loop, daemon=True, name="autosync").start()
    if BIND not in ("127.0.0.1", "localhost", "::1") and not AUTH.enabled:
        sys.exit("REFUS DE DÉMARRER : le hub écouterait sur "+BIND+" sans utilisateur. Définis HUB_PASSWORD pour créer l'administrateur au premier démarrage (ou garde HUB_BIND=127.0.0.1 et passe par un tunnel SSH).")
    srv = BoundedServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    log("info", f"Hub prêt : http://{BIND}:{PORT}  ({f'accès protégé : {len(AUTH.list_users())} utilisateur(s)' if AUTH.enabled else 'local uniquement'} ; LLM actif uniquement pour les contacts que tu actives)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for a in ACCOUNTS.values():
            a.shutdown()
