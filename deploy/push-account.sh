#!/usr/bin/env bash
# Envoie un compte déjà connecté (cookies + appareil chiffré + clé de l'historique) de ton ordinateur vers le VPS,
# SANS réenregistrer d'appareil chiffré sur Messenger.
# Usage : ./deploy/push-account.sh <nom-du-compte> utilisateur@serveur [dossier-du-projet-sur-le-vps]
set -euo pipefail
NAME="${1:?nom du compte}"; HOST="${2:?utilisateur@serveur}"; REMOTE="${3:-~/messenger-lite}"
SRC="accounts/$NAME"
