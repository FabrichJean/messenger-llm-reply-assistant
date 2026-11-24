#!/usr/bin/env bash
# Envoie un compte déjà connecté (cookies + appareil chiffré + clé de l'historique) de ton ordinateur vers le VPS,
# SANS réenregistrer d'appareil chiffré sur Messenger.
# Usage : ./deploy/push-account.sh <nom-du-compte> utilisateur@serveur [dossier-du-projet-sur-le-vps]
set -euo pipefail
NAME="${1:?nom du compte}"; HOST="${2:?utilisateur@serveur}"; REMOTE="${3:-~/messenger-lite}"
SRC="accounts/$NAME"
[ -f "$SRC/cookies.json" ] || { echo "Introuvable : $SRC/cookies.json"; exit 1; }
echo "Envoi de $SRC vers $HOST (cookies, e2ee.db, history_device.json) : ces fichiers sont des SECRETS."
read -r -p "Continuer ? [o/N] " ok; [ "$ok" = "o" ] || exit 1
umask 077
tar -C accounts -cz --exclude='.browser' --exclude='media' "$NAME" | ssh "$HOST" "cd $REMOTE && docker compose exec -T hub tar -C /data/accounts -xz && docker compose exec -T hub python3 /app/hub/adopt_account.py '$NAME' && docker compose restart hub"
echo "Terminé. Ne lance PLUS ce compte sur ton ordinateur en même temps : une seule session active par compte."
