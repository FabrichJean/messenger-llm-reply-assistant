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
- **Domaine** : ouvre `https://ton-domaine`.

## 6. Connecter Claude (le LLM)
- **Clé API** (facturée à l'usage, conseillée sur un serveur) : mets `ANTHROPIC_API_KEY=…` dans `.env`, puis `docker compose up -d`.
- **Compte Claude** : `docker compose exec -it hub claude` et suis la connexion. Elle est gardée dans le volume `hub-home`.

La consommation (tokens, coût, part servie par le cache) s'affiche dans **Statistiques**.

## 7. Ajouter un compte Messenger
Il n'y a pas de navigateur sur le serveur : la fenêtre Chrome de connexion n'existe pas ici. Deux façons :

**A. Envoyer un compte déjà connecté depuis ton ordinateur (conseillé pour tes comptes existants)** : les cookies **et** l'appareil chiffré (clés de l'historique) partent ensemble, rien n'est réenregistré chez Meta.
```bash
./deploy/push-account.sh fabrich utilisateur@serveur
```
Ensuite, **arrête ce compte sur ton ordinateur** : une seule session active par compte.

**B. Coller une session** : sur ton ordinateur, connecté à messenger.com, DevTools → Network → clic droit sur une requête → Copy → Copy as cURL ; puis dans le hub : Comptes → « coller une requête cURL ». Le compte arrive sans appareil chiffré : active-le ensuite avec « Enregistrer l'appareil chiffré » (une seule fois par compte).

> Attention : Meta peut demander une vérification quand une session apparaît depuis l'adresse IP d'un hébergeur (« connexion inhabituelle »). Si un compte tombe en « à reconnecter », reconnecte-toi depuis ton ordinateur et renvoie-le avec `push-account.sh`. Automatiser un compte personnel va aussi à l'encontre des conditions de Meta : garde des volumes raisonnables.

## 8. Reprendre tes conversations actuelles (facultatif)
Sinon, le hub repart de zéro et réimporte l'historique des conversations activées.
```bash
# sur ton ordinateur (copie propre de la base)
sqlite3 hub/hub.db ".backup /tmp/hub.db" && scp /tmp/hub.db utilisateur@serveur:/tmp/hub.db
# sur le VPS (hub arrêté)
docker compose stop hub && docker compose cp /tmp/hub.db hub:/data/hub.db && docker compose start hub
```
(`docker compose cp` demande que le conteneur existe ; si le volume refuse l'écriture, utilise `docker run --rm -v messenger-lite_hub-data:/data -v /tmp:/in alpine cp /in/hub.db /data/`.)

## 9. Sauvegardes, mises à jour, supervision
- **Sauvegarde chiffrée** : `./deploy/backup.sh ~/sauvegardes` (demande une phrase de passe). Elle contient des cookies et des clés : garde-la hors du serveur.
- **Mise à jour** : `git pull` (ou nouveau `rsync`) puis `docker compose up -d --build`. Les volumes sont conservés.
- **Journal** : `docker compose logs -f hub` ; santé : `docker compose ps` (« healthy »).
- **Redémarrage automatique** : `restart: unless-stopped` (le hub repart après un redémarrage du VPS).

## 10. Sécurité : ce qui est en place
- Mot de passe obligatoire hors du poste local, sessions de 7 jours (cookie `HttpOnly`, `SameSite=Strict`, `Secure` sous HTTPS), jetons gardés **hachés**, 5 essais par adresse puis blocage de 5 minutes.
- Écoute sur `127.0.0.1` du serveur ; HTTPS par Caddy ; en-têtes de sécurité.
- Conteneur non-root, système de fichiers en lecture seule, aucune capacité Linux, 1,5 Go de mémoire maximum.
- Secrets (cookies, clés chiffrées) uniquement dans le volume `hub-data`, fichiers en `600`.

Ce qui n'y est **pas** : plusieurs utilisateurs avec droits séparés (voir `MULTIUSER.md`) — un seul mot de passe donne accès à tous les comptes du hub.

## Dépannage
| Symptôme | Piste |
|---|---|
| `REFUS DE DÉMARRER … sans utilisateur` | `HUB_PASSWORD` vide dans `.env` et aucun utilisateur créé. |
| Page « host refusé » | Ajoute ton domaine dans `DOMAIN` (ou ouvre via `localhost` avec le tunnel). |
| Le LLM ne répond pas | `docker compose exec hub claude -p "test"` : connexion Claude absente ou clé invalide. |
| Compte « à reconnecter » | Session refusée par Meta : reconnecte-toi sur ton ordinateur puis `push-account.sh`. |
| Build qui échoue | Copie-moi la première erreur (image Go, paquet npm de Claude CLI ou version de Node). |
