#!/usr/bin/env python3
"""Gestion des utilisateurs du hub en ligne de commande (à lancer sur le serveur, jamais exposé au réseau).

  python3 users_cli.py list
  python3 users_cli.py add NOM [--admin] [--generate | --from-env]   # sans option : le mot de passe est demandé (saisie masquée)
  python3 users_cli.py reset NOM [--generate]
  python3 users_cli.py delete NOM

--from-env : prend le mot de passe dans la variable d'environnement HUB_PASSWORD (jamais affichée).
--generate : crée un mot de passe aléatoire fort et l'écrit dans <données>/initial-passwords.txt (0600), JAMAIS à l'écran.
Le dossier de données est HUB_DATA (par défaut : le dossier de hub.py).
"""
import getpass
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth  # noqa: E402

DATA = Path(os.environ.get("HUB_DATA", Path(__file__).resolve().parent))
os.umask(0o077)
A = auth.Auth(DATA)


def password(generate, name, from_env=False):
    if from_env:
        pw = os.environ.get("HUB_PASSWORD", "")
        if not pw:
            sys.exit("HUB_PASSWORD n'est pas défini")
        return pw
    if generate:
        pw = secrets.token_urlsafe(18)
        f = DATA / "initial-passwords.txt"
        with open(f, "a") as fh:
            fh.write(f"{name}\t{pw}\n")
        os.chmod(f, 0o600)
        print(f"mot de passe de « {name} » écrit dans {f} (non affiché)")
        return pw
    a, b = getpass.getpass("Mot de passe : "), getpass.getpass("Confirme : ")
    if a != b:
        sys.exit("les deux saisies diffèrent")
    return a


args = sys.argv[1:]
if not args:
    sys.exit(__doc__)
cmd, rest = args[0], [a for a in args[1:] if not a.startswith("--")]
flags = {a for a in args[1:] if a.startswith("--")}
try:
    if cmd == "list":
        for u in A.list_users():
            print(f"{u['name']}\t{u['role']}")
    elif cmd == "add" and rest:
        A.create_user(rest[0], password("--generate" in flags, rest[0], "--from-env" in flags), "admin" if "--admin" in flags else "user")
        print("utilisateur créé :", rest[0])
    elif cmd == "reset" and rest:
        A.set_password(rest[0], password("--generate" in flags, rest[0]))
        print("mot de passe réinitialisé :", rest[0])
    elif cmd == "delete" and rest:
        A.delete_user(rest[0])
        print("utilisateur supprimé :", rest[0])
    else:
        sys.exit(__doc__)
except ValueError as ex:
    sys.exit(f"erreur : {ex}")
