#!/usr/bin/env bash
# Sauvegarde chiffrée du hub (base, comptes avec leurs cookies et clés chiffrées, réglages).
# Usage : ./deploy/backup.sh [dossier-de-sortie]     (demande une phrase de passe ; à garder en lieu sûr)
set -euo pipefail
OUT="${1:-.}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
umask 077
# base SQLite copiée proprement (pas de copie à chaud du fichier ouvert)
docker compose exec -T hub python3 - <<'PY'
import sqlite3
src = sqlite3.connect("/data/hub.db"); dst = sqlite3.connect("/data/hub.backup.db"); src.backup(dst); dst.close(); src.close()
PY
docker compose exec -T hub tar -C /data --exclude=hub.db --exclude='hub.db-*' --exclude=sandbox --exclude=linkcache --exclude='accounts/*/media' --exclude='accounts/*/.browser' -cz . \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -out "$OUT/relais-$STAMP.tar.gz.enc"
docker compose exec -T hub rm -f /data/hub.backup.db
echo "Sauvegarde : $OUT/relais-$STAMP.tar.gz.enc"
echo "Restauration : openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in <fichier> | docker compose exec -T hub tar -C /data -xz   (puis : mv hub.backup.db hub.db)"
