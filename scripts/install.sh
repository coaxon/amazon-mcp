#!/usr/bin/env bash
# Amazon MCP — generic installer (run ON the target host, from project root).
#
# Usage:
#   sudo bash scripts/install.sh [options]
#
# Options:
#   --install-dir PATH   Install root (default: /opt/amazon-mcp)
#   --systemd            Install/refresh systemd unit (default when root)
#   --no-systemd         Skip systemd (Docker / manual run)
#   --seed-demo          Seed dry-run demo alert store
#   --verify             Run post-install health check
#   --python PATH        Python interpreter (default: python3)
#
# Environment:
#   AMAZON_MCP_INSTALL_DIR   Same as --install-dir
#   AMAZON_MCP_SERVICE_NAME    systemd unit name (default: amazon-mcp)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_DIR="${AMAZON_MCP_INSTALL_DIR:-/opt/amazon-mcp}"
SERVICE_NAME="${AMAZON_MCP_SERVICE_NAME:-amazon-mcp}"
DO_SYSTEMD=auto
SEED_DEMO=0
DO_VERIFY=0
PYTHON_BIN="${AMAZON_MCP_PYTHON:-python3}"

usage() {
  sed -n '2,20p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --systemd) DO_SYSTEMD=1; shift ;;
    --no-systemd) DO_SYSTEMD=0; shift ;;
    --seed-demo) SEED_DEMO=1; shift ;;
    --verify) DO_VERIFY=1; shift ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "[install] unknown option: $1" >&2; usage 1 ;;
  esac
done

if [[ "$DO_SYSTEMD" == auto ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    DO_SYSTEMD=1
  else
    DO_SYSTEMD=0
  fi
fi

log() { echo "[install] $*"; }
die() { echo "[install] ERROR: $*" >&2; exit 1; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python not found: $PYTHON_BIN"
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION#*.}"
[[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]] || die "Python 3.10+ required (found $PY_VERSION)"

# When installing to a different path, rsync/copy tree (invoked from deploy_remote).
# When already running inside INSTALL_DIR, skip copy.
if [[ "$(cd "$SRC_DIR" && pwd -P)" != "$(cd "$INSTALL_DIR" 2>/dev/null && pwd -P 2>/dev/null || echo __missing__)" ]]; then
  log "syncing ${SRC_DIR}/ -> ${INSTALL_DIR}/"
  mkdir -p "$INSTALL_DIR"
  rsync -a \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude '__pycache__/' \
    --exclude 'venv/' \
    --exclude '.venv/' \
    --exclude '.pytest_cache/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    "${SRC_DIR}/" "${INSTALL_DIR}/"
fi

cd "$INSTALL_DIR"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    log "created .env from .env.example (dry-run defaults)"
  else
    die "no .env or .env.example in ${INSTALL_DIR}"
  fi
else
  log ".env exists — not overwritten"
fi

if [[ ! -d venv ]]; then
  log "creating venv"
  "$PYTHON_BIN" -m venv venv
fi

log "installing Python dependencies"
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

mkdir -p data data/briefing_assets

if [[ "$SEED_DEMO" -eq 1 ]]; then
  log "seeding demo alert store"
  ./venv/bin/python scripts/seed_demo_briefing_store.py --multi || true
fi

if [[ "$DO_SYSTEMD" -eq 1 ]]; then
  UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
  log "writing systemd unit -> ${UNIT_PATH}"
  sed \
    -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
    -e "s|@SERVICE_NAME@|${SERVICE_NAME}|g" \
    "${SCRIPT_DIR}/amazon-mcp.service.in" > "$UNIT_PATH"
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}.service"
  systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active --quiet "${SERVICE_NAME}.service" || die "systemd service failed to start"
  log "systemd service active: ${SERVICE_NAME}"
fi

if [[ "$DO_VERIFY" -eq 1 ]]; then
  log "running health check"
  bash "${SCRIPT_DIR}/verify_install.sh" --install-dir "$INSTALL_DIR"
fi

log "done — install_dir=${INSTALL_DIR} dry_run=$(grep -E '^AMAZON_MCP_DRY_RUN=' .env | cut -d= -f2- || echo '?')"
