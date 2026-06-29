#!/usr/bin/env bash
# Deploy Amazon MCP to any SSH-accessible VPS.
#
# Usage:
#   bash scripts/deploy_remote.sh [user@host] [options]
#
# Options (passed to remote install.sh):
#   --install-dir PATH   Remote install root (default: /opt/amazon-mcp)
#   --dry-run            rsync dry-run only
#   --seed-demo          Seed demo data on remote
#   --no-restart         rsync only; skip remote install.sh
#
# Environment:
#   AMAZON_MCP_DEPLOY_HOST   Default SSH target (e.g. user@203.0.113.10)
#   AMAZON_MCP_INSTALL_DIR   Remote install path
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

REMOTE="${1:-${AMAZON_MCP_DEPLOY_HOST:-}}"
shift || true

INSTALL_DIR="${AMAZON_MCP_INSTALL_DIR:-/opt/amazon-mcp}"
DRY_RUN=0
SEED_DEMO=0
NO_RESTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --seed-demo) SEED_DEMO=1; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    *) echo "[deploy] unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$REMOTE" ]] || {
  echo "Usage: bash scripts/deploy_remote.sh user@host [--install-dir PATH]" >&2
  exit 1
}

RSYNC_OPTS=(-avz
  --exclude '.env'
  --exclude 'data/'
  --exclude '__pycache__/'
  --exclude 'venv/'
  --exclude '.venv/'
  --exclude '.pytest_cache/'
  --exclude '*.pyc'
  --exclude '.git/'
  --filter 'P .env'
  --filter 'P data/'
  --filter 'P venv/'
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[deploy] DRY-RUN rsync ${SRC_DIR}/ -> ${REMOTE}:${INSTALL_DIR}/"
  rsync "${RSYNC_OPTS[@]}" --dry-run "${SRC_DIR}/" "${REMOTE}:${INSTALL_DIR}/"
  exit 0
fi

echo "[deploy] rsync ${SRC_DIR}/ -> ${REMOTE}:${INSTALL_DIR}/"
rsync "${RSYNC_OPTS[@]}" "${SRC_DIR}/" "${REMOTE}:${INSTALL_DIR}/"

if [[ "$NO_RESTART" -eq 1 ]]; then
  echo "[deploy] --no-restart: rsync complete"
  exit 0
fi

INSTALL_ARGS=(--install-dir "$INSTALL_DIR" --systemd --verify)
[[ "$SEED_DEMO" -eq 1 ]] && INSTALL_ARGS+=(--seed-demo)

echo "[deploy] remote install: sudo bash ${INSTALL_DIR}/scripts/install.sh ${INSTALL_ARGS[*]}"
ssh -t "$REMOTE" "cd '${INSTALL_DIR}' && sudo bash scripts/install.sh ${INSTALL_ARGS[*]}"

echo "[deploy] done — ${REMOTE}:${INSTALL_DIR}"
