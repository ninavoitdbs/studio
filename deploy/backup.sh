#!/usr/bin/env bash
# Sauvegarde quotidienne du Studio du Bon Sens.
# Contenu de l'archive : base SQLite (copie coherente, meme pendant que l'appli ecrit),
# fichiers des contenus, brouillons, reglages (settings.json) et fichier env (secrets).
# Garde 7 sauvegardes quotidiennes + 4 hebdomadaires (dimanche) dans ~/backups/studio,
# puis copie hors serveur si STUDIO_BACKUP_REMOTE est defini (remote rclone chiffre).
# Lance par studio-backup.timer (systemd utilisateur) tous les jours a 03:30.
set -euo pipefail
umask 077

STUDIO="${STUDIO_DIR:-$HOME/studio}"
DEST="${BACKUP_DIR:-$HOME/backups/studio}"
ENV_FILE="${STUDIO_ENV_FILE:-$HOME/.config/studio/env}"
REMOTE="${STUDIO_BACKUP_REMOTE:-}"
KEEP_DAILY=7
KEEP_WEEKLY=4
REMOTE_MAX_AGE="${STUDIO_BACKUP_REMOTE_MAX_AGE:-35d}"

STAMP=$(date +%Y-%m-%d_%H%M)
NAME="studio_${STAMP}.tar.gz"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$DEST/daily" "$DEST/weekly" "$WORK/data"

# 1. Base SQLite : API de sauvegarde de SQLite (sure en mode WAL), puis controle d'integrite
python3 - "$STUDIO/data/studio.db" "$WORK/data/studio.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
src.close()
res = dst.execute("PRAGMA integrity_check").fetchone()[0]
n = dst.execute("SELECT count(*) FROM items").fetchone()[0]
dst.close()
if res != "ok":
    sys.exit(f"Base copiee mais integrite KO : {res}")
print(f"base ok ({n} contenus)")
PY

# 2. Fichiers
for d in items drafts; do
  if [ -d "$STUDIO/data/$d" ]; then cp -a "$STUDIO/data/$d" "$WORK/data/"; fi
done
if [ -f "$STUDIO/data/settings.json" ]; then cp -a "$STUDIO/data/settings.json" "$WORK/data/"; fi
if [ -f "$ENV_FILE" ]; then cp -a "$ENV_FILE" "$WORK/config-env"; fi

# 3. Archive
tar czf "$DEST/daily/$NAME.part" -C "$WORK" .
mv "$DEST/daily/$NAME.part" "$DEST/daily/$NAME"
if [ "$(date +%u)" = "7" ]; then
  cp -a "$DEST/daily/$NAME" "$DEST/weekly/$NAME"
fi

# 4. Rotation locale
rotate() {  # garde les $2 archives les plus recentes du dossier $1 (noms dates, tri lexical = chronologique)
  find "$1" -maxdepth 1 -name 'studio_*.tar.gz' -printf '%f\n' | sort -r | tail -n +$(($2 + 1)) \
    | while read -r f; do rm -f "$1/$f"; done
}
rotate "$DEST/daily" "$KEEP_DAILY"
rotate "$DEST/weekly" "$KEEP_WEEKLY"
echo "archive $DEST/daily/$NAME ($(du -h "$DEST/daily/$NAME" | cut -f1))"

# 5. Copie hors serveur (copy, jamais sync : une suppression locale ne doit pas effacer le distant)
if [ -n "$REMOTE" ]; then
  rclone copy "$DEST" "$REMOTE" --include "*/studio_*.tar.gz"
  rclone delete "$REMOTE" --min-age "$REMOTE_MAX_AGE" --include "daily/studio_*.tar.gz"
  rclone delete "$REMOTE" --min-age 120d --include "weekly/studio_*.tar.gz"
  echo "copie hors serveur ok ($REMOTE)"
else
  echo "ATTENTION : pas de copie hors serveur (STUDIO_BACKUP_REMOTE vide)"
fi

date -Iseconds > "$DEST/last_ok"
