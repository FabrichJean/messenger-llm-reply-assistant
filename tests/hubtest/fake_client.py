#!/usr/bin/env python3
"""Faux client « messenger-lite » pour les tests (lancé par le hub, dans le dossier du compte).

- annonce un compte connecté ;
- transmet au hub chaque ligne ajoutée à ./events.in (le test y « fait arriver » des messages) ;
- enregistre dans ./ops.jsonl chaque commande reçue du hub (envois, demandes d'historique, etc.).
"""
import json, os, sys, threading, time
def out(o): sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
out({"type": "self", "name": os.path.basename(os.getcwd()).capitalize()})
out({"type": "status", "state": "connected"})
out({"type": "status", "state": "e2ee_connected"})
def reader():
    for line in sys.stdin:
        with open("ops.jsonl", "a", encoding="utf-8") as f: f.write(line if line.endswith("\n") else line + "\n")
threading.Thread(target=reader, daemon=True).start()
pos = 0
while True:
    try:
        with open("events.in", "rb") as f:
            f.seek(pos); data = f.read(); pos += len(data)
        for line in data.decode("utf-8").splitlines():
            if line.strip(): sys.stdout.write(line + "\n"); sys.stdout.flush()
    except FileNotFoundError:
        pass
    time.sleep(0.05)
