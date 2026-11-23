#!/usr/bin/env python3
"""Déclare au hub un compte dont le dossier existe déjà (copié depuis ton ordinateur) : accounts/<nom>/cookies.json (+ e2ee.db, history_device.json).

Usage (dans le conteneur) :  python3 /app/hub/adopt_account.py <nom> [libellé]
Puis redémarre le hub : il lance le client de ce compte avec ses clés chiffrées d'origine (aucun nouvel appareil n'est enregistré).
"""
import json
import os
import re
import sys
from pathlib import Path

if len(sys.argv) < 2 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,19}", sys.argv[1]):
    sys.exit("Usage : adopt_account.py <nom> [libellé]   (nom : 2 à 20 caractères, minuscules, chiffres, - et _)")
name = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else ""
here = Path(__file__).resolve().parent
data = Path(os.environ.get("HUB_DATA", here))
root = Path(os.environ.get("HUB_ACCOUNTS_ROOT", here.parent / "accounts"))
cli = os.environ.get("HUB_CLIENT_BIN", str(here.parent / "messenger-lite"))
d = root / name
if not (d / "cookies.json").exists():
    sys.exit(f"Introuvable : {d}/cookies.json")
os.chmod(d, 0o700)
for f in d.glob("*"):
    if f.is_file():
        os.chmod(f, 0o600)
f = data / "accounts.json"
cfg = json.loads(f.read_text()) if f.exists() else []
if any(c["name"] == name for c in cfg):
    sys.exit(f"« {name} » est déjà déclaré.")
cfg.append({"name": name, "label": label, "dir": str(d), "bin": cli, "args": []})
tmp = data / "accounts.json.tmp"
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, f)
print(f"Compte « {name} » déclaré. Redémarre le hub : docker compose restart hub")
