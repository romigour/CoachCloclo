#!/usr/bin/env bash
# Installe Coach (macOS / Linux). Usage : curl -LsSf <URL>/install.sh | bash   ou   ./install.sh [--dry-run]
# Variables : COACH_SOURCE (wheel ou nom de paquet), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
# COACH_INSTALL_OFFLINE=1 (doctor sans Claude ni Garmin, pour la CI).
if [ -z "${BASH_VERSION:-}" ]; then
  echo "Ce script nécessite bash. Relance-le avec : curl -LsSf <URL>/install.sh | bash" >&2
  exit 1
fi
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "Option inconnue : $arg" >&2; exit 2 ;;
  esac
done

export PYTHONUTF8=1

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

# Commande interactive : lit le terminal même quand stdin est le tube de `curl | bash`.
run_interactive() {
  if [ "$DRY_RUN" = "1" ] || [ -t 0 ]; then
    run "$@"
  elif (: </dev/tty) 2>/dev/null; then
    "$@" </dev/tty
  else
    echo "Aucun terminal disponible : si une connexion est demandée, lance toi-même « coach doctor --fix »." >&2
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

FORCE=()
if [ "$DRY_RUN" = "0" ]; then
  TOOLS="$(uv tool list 2>/dev/null || true)"
  case "$TOOLS" in
    coach-running*|*$'\n'coach-running*) FORCE=(--force) ;;
  esac
fi

echo "Installation de Coach…"
run uv tool install --python 3.12 ${FORCE[@]+"${FORCE[@]}"} "$SOURCE"

echo "Vérification de l'installation…"
DOCTOR_ARGS=(doctor --fix)
if [ "${COACH_INSTALL_OFFLINE:-}" = "1" ]; then DOCTOR_ARGS+=(--offline); fi
if ! run_interactive coach "${DOCTOR_ARGS[@]}"; then
  echo "Certaines vérifications ont échoué (lignes ✗ ci-dessus). Corrige-les puis relance ce script." >&2
  exit 1
fi

if [ "${COACH_INSTALL_NO_START:-}" = "1" ]; then
  echo "Installation terminée (COACH_INSTALL_NO_START=1 : coach start non lancé)."
  exit 0
fi
run_interactive coach start
