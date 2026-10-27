#!/usr/bin/env bash
# Installe Coach (macOS / Linux). Usage : ./install.sh [--dry-run]
# Variables : COACH_SOURCE (wheel ou nom de paquet), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
# COACH_INSTALL_OFFLINE=1 (doctor sans Claude ni Garmin, pour la CI).
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Option inconnue : $arg" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

SOURCE="${COACH_SOURCE:-coach-running}"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installation de uv…"
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] curl -LsSf https://astral.sh/uv/install.sh | sh"
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi

FORCE=""
if [ "$DRY_RUN" = "0" ] && command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^coach-running'; then
  FORCE="--force"
fi

echo "Installation de Coach…"
if [ -n "$FORCE" ]; then
  run uv tool install --python 3.12 --force "$SOURCE"
else
  run uv tool install --python 3.12 "$SOURCE"
fi

echo "Vérification de l'installation…"
DOCTOR_ARGS=(doctor --fix)
[ "${COACH_INSTALL_OFFLINE:-}" = "1" ] && DOCTOR_ARGS+=(--offline)
if ! run coach "${DOCTOR_ARGS[@]}"; then
  echo "Certaines vérifications ont échoué (lignes ✗ ci-dessus). Corrige-les puis relance ce script." >&2
  exit 1
fi

if [ "${COACH_INSTALL_NO_START:-}" = "1" ]; then
  echo "Installation terminée (COACH_INSTALL_NO_START=1 : coach start non lancé)."
  exit 0
fi
run coach start
