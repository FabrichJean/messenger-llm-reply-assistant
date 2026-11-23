#!/usr/bin/env bash
# Sauvegarde chiffrée du hub (base, comptes avec leurs cookies et clés chiffrées, réglages).
# Usage : ./deploy/backup.sh [dossier-de-sortie]     (demande une phrase de passe ; à garder en lieu sûr)
set -euo pipefail
OUT="${1:-.}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
umask 077
# base SQLite copiée proprement (pas de copie à chaud du fichier ouvert)
