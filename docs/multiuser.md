# Multiuser — état et plan

## Principe
- **Il n'existe pas de compte « principal »** : l'application démarre sans aucun compte, et tous les comptes sont égaux.
- Chaque compte vit dans `accounts/<nom>/` (dossier en 700) avec ses propres secrets : `cookies.json`, `e2ee.db`, `history_device.json` (fichiers en 600). Rien de secret à la racine du projet.
- Les comptes se créent depuis l'application (« 👤 Comptes ») : fenêtre Chrome sur la vraie page officielle, ou collage d'un « Copy as cURL ». Le mot de passe ne passe jamais par l'application.

## Fait (phase 1 : isolation par compte)
- Chaque conversation appartient à un **compte** (clé `compte:identifiant`) : deux comptes peuvent avoir le même identifiant de fil sans collision.
- **Réglages par compte** (`account_settings`) avec repli sur les valeurs générales : nom, instructions, modèle, style, silence, limites, sécurité, mode leurre, synchro…
- **Style appris isolé** : les exemples de style et le profil ne sont jamais mélangés entre comptes.
- **Pause** par compte ; la **pause générale** prime sur tous les comptes.
- **Limite horaire globale par compte** (et non plus pour toute l'installation).
- Interface : filtre par compte, fenêtre de réglages « Général / Compte … », réinitialisation des réglages d'un compte.

## À faire (phase 2 : plusieurs utilisateurs avec connexion) — à valider avant de coder
1. **Authentification** : comptes utilisateurs (mot de passe haché scrypt), sessions (cookie HttpOnly, SameSite=Strict), limitation des essais, rôles admin / utilisateur.
2. **Propriété** : chaque compte Messenger appartient à un utilisateur ; chaque route d'API vérifie « cet utilisateur possède-t-il ce compte ? » (aujourd'hui aucune vérification, le hub n'écoute qu'en local).
3. **Secrets isolés** : un dossier par compte (`cookies.json`, `e2ee.db`, `history_device.json`) en permissions 700/600 ; ne jamais exposer ces fichiers via l'API.
4. **Claude** : aujourd'hui tous les appels utilisent la connexion Claude de la machine (un seul abonnement). Pour plusieurs utilisateurs : une clé API par utilisateur (variable `ANTHROPIC_API_KEY` propre à chaque compte, déjà transmise par l'environnement nettoyé) et des quotas.
5. **Exposition** : HTTPS via un reverse proxy (Caddy / nginx) devant le hub ; ne jamais ouvrir le port du hub directement.
6. **Quotas et audit** : limites par utilisateur (réponses/heure, comptes), journal d'audit (qui a activé quoi).
7. **Onboarding** : assistant d'ajout de compte (cookies, enregistrement de l'appareil chiffré avec confirmation, PIN), une étape explicite par action qui modifie le compte Messenger.

## Questions ouvertes (décisions de produit)
- Qui sont les utilisateurs : toi seul avec plusieurs comptes, une équipe de confiance, ou des tiers ?
- Qui paie l'usage de Claude (abonnement partagé ou clés individuelles) ?
- Hébergement : VPS unique ? Domaine et HTTPS ?

## Avertissements
- Automatiser un compte Messenger personnel va contre les conditions de Meta : chaque utilisateur doit le savoir et l'accepter pour ses propres comptes.
- Héberger les sessions (cookies) d'autres personnes engage ta responsabilité (sécurité, RGPD) : à n'envisager qu'avec leur accord éclairé.

## Déploiement VPS
Voir `deploy/README.md` : Docker, mot de passe unique (`HUB_PASSWORD`, obligatoire hors poste local), tunnel SSH ou HTTPS par Caddy, envoi de comptes déjà connectés. Les rôles et la propriété des comptes par utilisateur (phase 2 ci-dessus) restent à faire.
