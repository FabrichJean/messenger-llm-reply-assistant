# Déployer Relais sur un VPS

Le hub tourne dans Docker : un conteneur avec le hub (Python), le client Messenger (Go) et Claude CLI. Les données (base, comptes, clés chiffrées) vivent dans des volumes Docker, **jamais dans l'image**.

> ⚠️ Ces fichiers n'ont pas encore été construits sur une vraie machine (voir « Premier démarrage »). Fais un premier essai et note la première erreur éventuelle : elle se corrige en une ligne.

## 1. Ce qu'il te faut
- Un VPS Linux (Ubuntu ou Debian récent), **2 Go de RAM** conseillés (1 Go au minimum), 10 Go de disque.
- Docker + le plugin compose : `curl -fsSL https://get.docker.com | sh` puis `sudo usermod -aG docker $USER` (reconnecte-toi).
- Accès SSH par clé (désactive la connexion par mot de passe).
- Pour un accès par adresse web : un nom de domaine dont l'enregistrement A pointe vers le VPS. Sinon, un tunnel SSH suffit.

## 2. Pare-feu (à faire d'abord)
```bash
sudo ufw default deny incoming && sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp        # seulement si tu utilises un domaine (Caddy)
sudo ufw enable
```
Le port 8787 du hub n'est **jamais** ouvert à Internet : il n'écoute que sur `127.0.0.1` du serveur.

## 3. Copier le projet
Depuis ton ordinateur (sans tes secrets) :
```bash
rsync -az --exclude accounts --exclude .venv --exclude '*.db*' --exclude cookies.json --exclude .git ./ utilisateur@serveur:~/messenger-lite/
```

## 4. Configurer
Sur le VPS :
```bash
cd ~/messenger-lite && cp deploy/.env.example .env && chmod 600 .env && nano .env
```
- `HUB_PASSWORD` : **obligatoire au premier démarrage** : mot de passe de l'administrateur (`HUB_ADMIN_USER`, « admin » par défaut), 12 caractères minimum. Il ne sert qu'à créer l'administrateur ; ensuite les mots de passe se changent dans l'interface.

### Plusieurs utilisateurs (mode SaaS)
Chaque utilisateur a son identifiant et son mot de passe, et ne voit que SES comptes Messenger (conversations, médias, réglages, journal, statistiques).
L'administrateur crée les utilisateurs depuis le menu « Utilisateurs » (il ne lit pas leurs conversations). Chaque utilisateur ajoute ses propres comptes ; un compte Messenger déjà relié à quelqu'un d'autre est refusé.
En ligne de commande (hub arrêté, sinon il écraserait le fichier) :
```
docker compose stop hub
docker compose run --rm --no-deps hub python3 hub/users_cli.py add marie --generate   # mot de passe aléatoire écrit dans /data/initial-passwords.txt, jamais affiché
docker compose up -d hub
```
Un compte existant est rattaché à l'utilisateur du même nom, sinon à l'administrateur. Claude est partagé (une seule connexion `claude` sur le serveur) : les limites de réponses/heure se règlent par compte.
- `DOMAIN` + `HUB_TRUST_PROXY=1` + `HUB_SECURE_COOKIE=1` si tu veux l'accès par `https://ton-domaine`.
- `ANTHROPIC_API_KEY` : voir l'étape 6.

## 5. Premier démarrage
```bash
docker compose up -d --build            # tunnel SSH
# ou, avec un domaine (certificat HTTPS automatique) :
COMPOSE_PROFILES=https docker compose up -d --build
docker compose ps && docker compose logs -f hub
```
- **Tunnel SSH** (le plus sûr) : sur ton ordinateur `ssh -L 8787:127.0.0.1:8787 utilisateur@serveur`, puis ouvre <http://localhost:8787> et entre le mot de passe.
