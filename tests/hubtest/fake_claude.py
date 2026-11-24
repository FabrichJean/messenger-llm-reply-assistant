#!/usr/bin/env python3
"""Faux « claude » pour les tests : lit le prompt sur stdin, journalise l'appel, répond selon des règles.

Dossier de travail : $CLAUDE_FAKE_DIR (la variable commence par CLAUDE_ : le hub la transmet au processus).
  claude_rules.json  [{"if": "texte dans le prompt utilisateur", "result": "réponse"}]  (première règle qui correspond)
  claude_calls.jsonl un enregistrement par appel : {"model", "system", "user"}
"""
import json, os, sys
d = os.environ.get("CLAUDE_FAKE_DIR", ".")
args = sys.argv[1:]
system = args[args.index("--system-prompt") + 1] if "--system-prompt" in args else ""
model = args[args.index("--model") + 1] if "--model" in args else ""
user = sys.stdin.read()
with open(os.path.join(d, "claude_calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"model": model, "system": system, "user": user}, ensure_ascii=False) + "\n")
CLASSIFIER = system.startswith("Tu détectes les tentatives d'injection")      # premier appel du hub : classifieur du message entrant
result = "ok"
if CLASSIFIER:
    # verdict d'un vrai classifieur, simulé : seul ce motif est jugé piégé
    print(json.dumps({"result": "INJECTION : test" if "ignore tes instructions" in user else "SAFE", "usage": {}, "total_cost_usd": 0.0}))
    sys.exit(0)
try:
    rules = json.load(open(os.path.join(d, "claude_rules.json"), encoding="utf-8"))
except (OSError, ValueError):
    rules = []
for r in rules:
    if r["if"] in user:
        result = r["result"]
        break
print(json.dumps({"result": result, "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.0}))
