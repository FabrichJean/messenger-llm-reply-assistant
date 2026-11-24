#!/usr/bin/env python3
"""Crée accounts/<nom>/cookies.json à partir du presse-papiers (ou de stdin).

Usage :  python3 tools/import_cookies.py <nom-du-compte>

Accepte :
  - une commande « Copy as cURL » (DevTools > Network > clic droit > Copy > Copy as cURL) faite sur messenger.com
  - ou la valeur d'un en-tête Cookie : "datr=...; c_user=...; xs=..."
Les valeurs ne sont jamais affichées. Dossier en 700, fichier en 600. Il n'y a pas de compte « principal » :
chaque compte vit dans son propre dossier. (Le plus simple reste « 👤 Comptes » dans l'application.)
"""
import json
import os
import re
import subprocess
import sys

NEEDED = ["c_user", "xs", "datr"]
OPTIONAL = ["sb", "fr", "wd", "presence", "dpr", "oo"]

if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,19}", sys.argv[1]):
    sys.exit("Usage : python3 tools/import_cookies.py <nom-du-compte>   (2 à 20 caractères : minuscules, chiffres, - et _)")
name = sys.argv[1]

data = sys.stdin.read() if not sys.stdin.isatty() else subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
if not data.strip():
    sys.exit("Presse-papiers vide.")

m = re.search(r"""(?:-b|--cookie)\s+(['"])(.*?)\1""", data, re.S) or \
    re.search(r"""-H\s+(['"])\s*cookie:\s*(.*?)\1""", data, re.S | re.I)
header = m.group(2) if m else data

cookies = {}
for part in re.split(r";\s*", header.strip()):
    if "=" in part:
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip().strip("'\"")

missing = [k for k in NEEDED if not cookies.get(k)]
if missing:
    sys.exit(f"Cookies manquants dans le presse-papiers : {missing}\n"
             "Copie une requête (cURL) vers messenger.com, pas la page elle-même.")

out = {k: cookies[k] for k in NEEDED + OPTIONAL if cookies.get(k)}
root = os.environ.get("HUB_ACCOUNTS_ROOT") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "accounts")   # comme le hub : <racine du dépôt>/accounts
folder = os.path.join(root, name)
os.makedirs(folder, mode=0o700, exist_ok=True)
os.chmod(folder, 0o700)
fd = os.open(os.path.join(folder, "cookies.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(out, f, indent=2)
print(f"accounts/{name}/cookies.json écrit ({', '.join(out)}) — valeurs non affichées.")
