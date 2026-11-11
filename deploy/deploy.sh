#!/usr/bin/env bash
# Deploie la derniere version de main (GitHub ninavoitdbs/studio) sur nina-vps.
# Depuis le PC, apres un git push :   ssh nina-vps ~/studio/deploy/deploy.sh
#
# 1. refuse de continuer si quelqu'un a modifie des fichiers directement sur le serveur ;
# 2. recupere main (avance rapide uniquement, jamais de fusion) ;
# 3. reinstalle les dependances si requirements.lock a change, met a jour les unites systemd ;
# 4. redemarre le Studio et attend /healthz ;
# 5. si le Studio ne repond pas : retour automatique a la version precedente.
set -euo pipefail
cd "${STUDIO_DIR:-$HOME/studio}"
BRANCH="${1:-main}"
UNITS="$HOME/.config/systemd/user"

if [ -n "$(git status --porcelain)" ]; then
  echo "Des fichiers ont ete modifies directement sur le serveur :"
  git status -s
  echo "Deploiement annule. Les committer (ou les annuler) d'abord."
  exit 1
fi

PREV=$(git rev-parse HEAD)
git fetch -q origin "$BRANCH"
git merge -q --ff-only "origin/$BRANCH"
NEW=$(git rev-parse HEAD)
if [ "$PREV" = "$NEW" ]; then
  echo "Deja a jour ($(git log -1 --format='%h %s'))."
  exit 0
fi
echo "Deploiement de :"
git log --oneline "$PREV..$NEW"

apply() {  # $1 = version d'avant, $2 = version a appliquer (deja extraite)
  if ! git diff --quiet "$1" "$2" -- requirements.lock; then
    echo "Dependances modifiees : installation..."
    venv/bin/pip install -q -r requirements.lock
  fi
  install -m 644 deploy/studio.service deploy/studio-backup.service deploy/studio-backup.timer "$UNITS/"
  systemctl --user daemon-reload
  systemctl --user restart studio
}

healthy() {
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null http://127.0.0.1:8787/healthz && return 0
    sleep 2
  done
  return 1
}

apply "$PREV" "$NEW"
if healthy; then
  echo "OK : le Studio tourne en $(git log -1 --format='%h %s')"
  exit 0
fi

echo "ECHEC : le Studio ne repond pas. Retour a la version precedente ($PREV)..."
journalctl --user -u studio -n 20 --no-pager -o cat || true
git reset -q --hard "$PREV"
apply "$NEW" "$PREV"
if healthy; then
  echo "Version precedente remise en place, le Studio repond."
else
  echo "ATTENTION : le Studio ne repond toujours pas. Voir : journalctl --user -u studio -n 50"
fi
exit 1
