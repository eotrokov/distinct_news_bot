#!/usr/bin/env bash
# Deploy distinct-news-bot next to other bots on a remote VPS.
#
# Required env:
#   DEPLOY_HOST
#   DEPLOY_USER
#
# Optional:
#   DEPLOY_PATH       default: /opt/distinct-news-bot
#   DEPLOY_SSH_KEY    path to private key
#   DEPLOY_SSH_PORT   default: 22
#   DEPLOY_BRANCH     default: main
#
# Example:
#   DEPLOY_HOST=1.2.3.4 DEPLOY_USER=ubuntu ./deploy/deploy.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"

DEPLOY_PATH="${DEPLOY_PATH:-/opt/distinct-news-bot}"
DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"

SSH_OPTS=(-p "$DEPLOY_SSH_PORT" -o StrictHostKeyChecking=accept-new)
if [[ -n "${DEPLOY_SSH_KEY:-}" ]]; then
  SSH_OPTS+=(-i "$DEPLOY_SSH_KEY")
fi

REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"
ssh_cmd() { ssh "${SSH_OPTS[@]}" "$REMOTE" "$@"; }
rsync_ssh() { printf 'ssh'; printf ' %q' "${SSH_OPTS[@]}"; }

echo "==> Ensuring remote directories and rsync/docker exist"
ssh_cmd "mkdir -p $(printf %q "$DEPLOY_PATH")/data; \
  if ! command -v rsync >/dev/null 2>&1; then \
    export DEBIAN_FRONTEND=noninteractive; \
    (command -v apt-get >/dev/null && apt-get update -qq && apt-get install -y -qq rsync >/dev/null) || true; \
  fi; \
  if ! command -v docker >/dev/null 2>&1; then \
    echo 'Docker is not installed on the server' >&2; exit 1; \
  fi"

echo "==> Syncing project files to $REMOTE:$DEPLOY_PATH"
RSYNC_RSH="$(rsync_ssh)"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude '*.sqlite3' \
  -e "$RSYNC_RSH" \
  "$ROOT_DIR/" \
  "$REMOTE:$DEPLOY_PATH/"

echo "==> Checking remote .env"
if ! ssh_cmd "test -f $(printf %q "$DEPLOY_PATH")/.env"; then
  cat >&2 <<EOF
Remote is missing $DEPLOY_PATH/.env

On the server, create it once:
  cd $DEPLOY_PATH
  cp deploy/env.production.example .env
  # edit TELEGRAM_BOT_TOKEN (and optional RSSHUB_BASE_URL), then re-run this script
EOF
  exit 1
fi

echo "==> Building and restarting container (branch hint: $DEPLOY_BRANCH)"
ssh_cmd "cd $(printf %q "$DEPLOY_PATH") && \
  docker image prune -af >/dev/null 2>&1 || true; \
  docker builder prune -af >/dev/null 2>&1 || true; \
  docker compose up -d --build --remove-orphans && docker compose ps"

echo "==> Recent logs"
ssh_cmd "cd $(printf %q "$DEPLOY_PATH") && docker compose logs --tail=40 bot"

echo "==> Deploy finished"
