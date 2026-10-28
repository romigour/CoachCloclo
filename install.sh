#!/usr/bin/env bash
# Installe CoachCloclo (macOS / Linux). Usage : curl -LsSf https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.sh | bash   ou   ./install.sh [--dry-run]
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

# Source par défaut : la wheel de la dernière release GitHub (front déjà compilé).
latest_wheel() {
  curl -fsSL https://api.github.com/repos/romigour/CoachCloclo/releases/latest \
    | grep -o '"browser_download_url": *"[^"]*\.whl"' | head -n 1 | sed 's/.*"\(https[^"]*\)"$/\1/'
}
if [ -n "${COACH_SOURCE:-}" ]; then
  SOURCE="$COACH_SOURCE"
elif [ "$DRY_RUN" = "1" ]; then
  SOURCE="<wheel de la dernière release GitHub>"
else
  SOURCE="$(latest_wheel || true)"
  if [ -z "$SOURCE" ]; then
    echo "Aucune release publiée sur https://github.com/romigour/CoachCloclo/releases (ou GitHub injoignable)." >&2
    exit 1
  fi
fi
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
    coachcloclo*|*$'\n'coachcloclo*) FORCE=(--force) ;;
  esac
fi

echo "Installation de CoachCloclo…"
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
