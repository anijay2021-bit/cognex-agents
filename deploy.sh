#!/bin/bash
# COGNEX deploy: repo -> deployed dirs, restart only changed services.
# Usage: ./deploy.sh   (run from anywhere; pulls latest main first)
set -euo pipefail
REPO="$HOME/cognex-agents"
COMPONENTS="cognex-dashboard prajnan-agent prajnan-agent2 nitin-agent trishul-agent pocket-pivot-agent"
cd "$REPO"
git pull --ff-only
changed=""
for d in $COMPONENTS; do
  [ -d "$REPO/$d" ] || continue
  find "$REPO/$d" -name '*.py' -not -path '*venv*' -print0 | xargs -0 -r -n50 python3 -m py_compile
  out=$(rsync -aic --exclude=venv --exclude=__pycache__ --exclude=logs --exclude='*.log' --exclude='*.db' --exclude='.env' --exclude='*.json' --exclude='*.bak*' --exclude='*.orig*' --exclude='*.service' "$REPO/$d/" "$HOME/$d/" | grep -v '^\.d' || true)
  if [ -n "$out" ]; then
    echo "[deploy] $d changed:"; echo "$out" | head -20
    changed="$changed $d"
  fi
done
for s in $changed; do
  echo "[deploy] try-restart $s"
  sudo systemctl try-restart "$s"
done
if [ -z "$changed" ]; then echo "[deploy] nothing to do"; else echo "[deploy] done:$changed"; fi
