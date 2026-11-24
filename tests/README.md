# Tests

Filet de sécurité de la restructuration : ils décrivent le comportement **actuel** du hub et ne doivent pas changer quand on déplace du code.

```bash
tests/run.sh          # tout (Go + hub)
tests/run.sh hub      # hub seulement (~40 s)
```

## Principe

Les tests du hub sont des tests « boîte noire » : `hubtest/harness.py` lance le vrai `hub/hub.py` dans un dossier temporaire, avec

- un **faux client Messenger** (`fake_client.py`) : il annonce un compte connecté, fait « arriver » des messages (fichier `events.in`) et enregistre ce que le hub lui demande d'envoyer (`ops.jsonl`) ;
- un **faux `claude`** (`fake_claude.py`) : il répond selon des règles et journalise chaque prompt (`claude_calls.jsonl`) ;
- un petit client HTTP avec cookie de session et en-tête CSRF.

Aucun test n'importe `hub.py` : ils ne dépendent donc pas de l'organisation interne du code.

| Fichier | Couvre |
|---|---|
| `test_hub_http.py` | pages publiques, authentification, CSRF, contrôle d'hôte, en-têtes de sécurité, CSP |
| `test_hub_users.py` | utilisateurs, invitations, mots de passe, **isolation** entre utilisateurs (lecture, écriture, administrateur) |
| `test_hub_replies.py` | réponse automatique de bout en bout, prompts, mémoire ciblée, brouillons, sujets sensibles, urgences, messages piégés, anti-tic, reprise en main, limites |
| `test_hub_api.py` | routes utilisées par l'interface (réglages, mémoire, envoi, épinglage, suppression, extension) |
| `test_pure_modules.py` | `humanize`, `memory`, `security`, `auth` (importés directement, à plat ou dans `relais/`) |

Les données de test sont fictives. Rien n'est écrit en dehors du dossier temporaire.
