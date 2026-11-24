# Sécurité

Ce document décrit ce que Relais protège, comment, et comment le vérifier. Les protections sont couvertes par des **tests d'attaque automatisés** (`tests/test_security_*.py`) rejoués à chaque exécution de `tests/run.sh`.

## Qui peut attaquer

| Attaquant | Ce qu'il peut tenter |
|---|---|
| **Un contact Messenger malveillant** | Envoyer des messages, liens et pièces jointes piégés : injection de consignes dans le LLM, XSS dans l'interface, requêtes vers le réseau interne (SSRF), falsification de l'historique que lit le modèle |
| **Un utilisateur du hub** | Lire ou modifier les conversations, comptes, médias et réglages d'un autre utilisateur ; s'élever en administrateur |
| **Un visiteur anonyme / le réseau** | Forcer un mot de passe, abuser des invitations, requêtes HTTP malformées ou géantes, usurper une adresse, détourner une session |
| **Un contenu hostile côté serveur** | Fuite de secrets (cookies Messenger, mots de passe) dans les journaux, les erreurs ou les fichiers |

## Protections, par couche

**Accès et sessions**
- Mots de passe hachés avec `scrypt` (sel unique), 12 caractères minimum ; comparaison à temps constant ; durée de réponse identique que l'identifiant existe ou non.
- Sessions : jeton de 256 bits, seule son empreinte est stockée, liées au mot de passe (un changement ferme toutes les sessions), 20 sessions maximum par utilisateur, cookie `HttpOnly`, `SameSite=Strict` et préfixe `__Host-` derrière HTTPS.
- Blocage des essais par adresse (et global) ; l'adresse du client derrière un proxy est la **dernière** entrée de `X-Forwarded-For`, jamais le début que le client peut écrire.
- Invitations : jeton de 192 bits, empreinte seule conservée, usage unique même sous requêtes simultanées, jamais le rôle administrateur.
- Protection CSRF (en-tête personnalisé) et contrôle strict de l'en-tête `Host`.

**Isolation entre utilisateurs**
- Chaque route d'écriture vérifie la propriété de la conversation, du compte ou du brouillon visé ; les lectures (état, statistiques, médias, avatars) sont filtrées. L'administrateur gère les utilisateurs mais ne lit pas les conversations des autres.

**Couche HTTP**
- Longueur du corps validée avant lecture, limitée par route (64 Ko avant connexion, 2 Mo ensuite), délai total de réception, identité vérifiée avant de lire un gros corps, plafond de connexions, délai d'inactivité.
- En-têtes : CSP sans `unsafe-inline` pour les scripts (chaque script en ligne autorisé par empreinte), `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, politique de permissions fermée.

**Interface**
- Le contenu venant d'un contact est toujours inséré comme **texte**, jamais comme HTML ; les liens n'acceptent que `http(s)` (vérifié côté client Go et côté hub) ; les types de fichiers sont déterminés par le contenu, jamais par ce que le message annonce.

**Requêtes sortantes (SSRF)**
- Aperçus de liens, avatars et médias : schémas `http(s)`, ports 80/443, adresses **publiques seulement** (liste d'autorisation : exclut aussi `100.64.0.0/10`, IPv6 embarquant de l'IPv4, 6to4, NAT64), adresse résolue puis **épinglée** (pas de second DNS), redirections revalidées à chaque saut, taille limitée, aucune session envoyée hors des domaines Meta.

**LLM**
- Appel sans aucun outil, dans un dossier vide, avec un environnement minimal.
- Messages du contact : nettoyés (caractères invisibles et de contrôle, marqueurs neutralisés), **sur une seule ligne** (impossible de simuler un tour de parole du propriétaire), encadrés par un délimiteur à jeton aléatoire, traités comme des données non fiables.
- Détection locale des messages piégés (déguisés ou non : homoglyphes, caractères invisibles, leet, lettres espacées, base64, rot13, hexadécimal, plusieurs langues), classifieur LLM, puis contrôle de la **réponse** avant envoi (liens, e-mails, numéros, mots de passe, format interne, fuite du prompt ou d'un marqueur secret) et second contrôle par un juge.
- La mémoire d'un contact ne retient ni lien, ni numéro, ni mot de passe, ni consigne piégée, et reste isolée par contact.

**Secrets**
- Cookies, clés chiffrées et sessions : fichiers en `0600`, dossiers en `0700`, jamais dans les journaux ni dans les erreurs renvoyées.
- Conteneur : utilisateur non-root, système de fichiers en lecture seule, aucune capacité, `no-new-privileges`, port lié à `127.0.0.1`.
- Dépendances : `govulncheck` sans vulnérabilité atteignable ; compilateur Go et Claude CLI à version figée dans le `Dockerfile`.
- Application Android : sauvegardes désactivées, aucun trafic en clair, navigation limitée au hub, accès aux fichiers coupé.

## Vérifier

```bash
tests/run.sh                                  # tout, y compris les tests de sécurité
cd tests && python3 -m unittest test_security_authz test_security_auth test_security_http \
    test_security_ssrf test_security_secrets test_security_prompt_injection test_security_reply_filter test_security_scripts
.venv/bin/python -m unittest discover -s tests -p "test_security_xss.py"      # XSS dans un vrai navigateur (Playwright)
govulncheck ./...                             # dépendances du client Go
```

| Test | Attaque simulée |
|---|---|
| `test_security_authz.py` | 44 attaques d'un utilisateur contre les ressources d'un autre (toutes les routes d'écriture, types piégés, injection SQL) |
| `test_security_auth.py` | force brute, usurpation d'adresse, session forgée ou fixée, invitations en parallèle, énumération par la durée |
| `test_security_http.py` | `Content-Length` piégé, corps géants, JSON hostile, requêtes malformées, `Host` piégé, connexions lentes |
| `test_security_xss.py` | charge XSS dans 11 champs contrôlés par un contact, vérifiée dans le navigateur |
| `test_security_ssrf.py` | adresses internes sous toutes leurs écritures, redirections, fuite de session |
| `test_security_secrets.py` | permissions des fichiers, secrets dans les journaux, erreurs et fichiers de données |
| `test_security_prompt_injection.py` | attaques d'injection (21) et vrais messages (≈ 55) : détecter sans bloquer à tort ; falsification de l'historique |
| `test_security_reply_filter.py` | réponses hostiles obtenues par injection, réponses normales jamais bloquées |
| `test_security_scripts.py` | scripts de déploiement : validation des valeurs injectées dans SSH, chiffrement des sauvegardes |

## Limites connues

- **Le LLM n'est pas déterministe** : les défenses se cumulent (détection locale, classifieur, contrôle de la réponse, juge) mais aucune ne garantit à elle seule qu'un modèle ne sera jamais trompé. Les sujets sensibles (argent, engagements, conflits) sont transmis au propriétaire.
- **Le blocage global des essais de connexion** est un compromis : il protège d'une attaque distribuée mais peut gêner temporairement les connexions légitimes pendant celle-ci.
- **Les mots de passe initiaux** créés par `users_cli.py --generate` sont écrits dans `initial-passwords.txt` : à récupérer puis à vider.
- **TLS, pare-feu et certificats** relèvent de l'hébergeur / du proxy placé devant le hub ; le hub ne doit jamais être exposé directement.
- **Automatiser un compte Messenger** va à l'encontre des conditions de Meta : voir l'avertissement du README.
- Aucun audit **externe** n'a été réalisé : les tests ci-dessus sont un audit interne, rejoué automatiquement.

## Signaler une faille

Ouvre une *issue* sans y publier de détails exploitables, ou contacte directement l'auteur du dépôt.
