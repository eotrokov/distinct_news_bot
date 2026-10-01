#!/usr/bin/env bash
# Deploy distinct-news-bot next to other bots on a remote VPS.
#
# Required env:
#   DEPLOY_HOST
#   DEPLOY_USER
#
# Auth (one of):
#   DEPLOY_SSH_KEY       path to private key
#   DEPLOY_SSH_PASSWORD  password for sshpass (used when no key, or as fallback)
#
# Optional:
#   DEPLOY_PATH       default: /opt/distinct-news-bot
#   DEPLOY_SSH_PORT   default: 22
#   DEPLOY_BRANCH     default: main
#
# Example:
#   DEPLOY_HOST=1.2.3.4 DEPLOY_USER=ubuntu ./deploy/deploy.sh
#   DEPLOY_HOST=1.2.3.4 DEPLOY_USER=root DEPLOY_SSH_PASSWORD='...' ./deploy/deploy.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${DEPLOY_HOST:?Set DEPLOY_HOST}"
: "${DEPLOY_USER:?Set DEPLOY_USER}"

DEPLOY_PATH="${DEPLOY_PATH:-/opt/distinct-news-bot}"
DEPLOY_SSH_PORT="${DEPLOY_SSH_PORT:-22}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"

SSH_OPTS=(-p "$DEPLOY_SSH_PORT" -o StrictHostKeyChecking=accept-new)
if [[ -n "${DEPLOY_SSH_KEY:-}" ]]; then
  SSH_OPTS+=(-i "$DEPLOY_SSH_KEY" -o IdentitiesOnly=yes -o PreferredAuthentications=publickey,password)
else
  SSH_OPTS+=(-o PreferredAuthentications=password -o PubkeyAuthentication=no)
fi

USE_SSHPASS=0
if [[ -n "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "DEPLOY_SSH_PASSWORD is set but sshpass is not installed" >&2
    exit 1
  fi
  export SSHPASS="$DEPLOY_SSH_PASSWORD"
  USE_SSHPASS=1
fi

if [[ -z "${DEPLOY_SSH_KEY:-}" && "$USE_SSHPASS" -ne 1 ]]; then
  echo "Set DEPLOY_SSH_KEY (path) or DEPLOY_SSH_PASSWORD" >&2
  exit 1
fi

REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"

ssh_cmd() {
  if [[ "$USE_SSHPASS" -eq 1 ]]; then
    sshpass -e ssh "${SSH_OPTS[@]}" "$REMOTE" "$@"
  else
    ssh "${SSH_OPTS[@]}" "$REMOTE" "$@"
  fi
}

rsync_ssh() {
  if [[ "$USE_SSHPASS" -eq 1 ]]; then
    # rsync -e expects a single command string.
    printf 'sshpass -e ssh'
    printf ' %q' "${SSH_OPTS[@]}"
  else
    printf 'ssh'
    printf ' %q' "${SSH_OPTS[@]}"
  fi
}

echo "==> Ensuring remote directories and rsync/docker exist"
ssh_cmd "mkdir -p $(printf %q "$DEPLOY_PATH")/data; \
  if ! command -v rsync >/dev/null 2>&1; then \
    export DEBIAN_FRONTEND=noninteractive; \
    (command -v apt-get >/dev/null && apt-get update -qq && apt-get install -y -qq rsync >/dev/null) || true; \
  fi; \
  if ! command -v docker >/dev/null 2>&1; then \
    echo 'Docker is not installed on the server' >&2; exit 1; \
  fi"

echo "==> Freeing disk space on remote before sync"
# Keep tagged images (incl. python base) so builds work when Docker Hub is unreachable.
# Do not prune volumes — bot-data must survive deploys.
ssh_cmd "df -h / | tail -1; \
  docker container prune -f >/dev/null 2>&1 || true; \
  docker image prune -f >/dev/null 2>&1 || true; \
  docker builder prune -af --filter until=168h >/dev/null 2>&1 || true; \
  (command -v apt-get >/dev/null && apt-get clean >/dev/null 2>&1) || true; \
  rm -rf /tmp/pip-* /var/tmp/pip-* >/dev/null 2>&1 || true; \
  df -h / | tail -1"

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
# Prefer local base images so deploys survive Docker Hub / IPv6 outages.
# Prefer IPv4 for registry auth (this VPS often cannot reach Docker Hub over IPv6).
# If python:3.12-slim was pruned, retag the app image as a temporary base.
# Older compose parses --pull as bool (true/false), not never/always.
ssh_cmd "cd $(printf %q "$DEPLOY_PATH") && \
  docker builder prune -f --filter until=72h >/dev/null 2>&1 || true; \
  if [ -f /etc/gai.conf ] || sudo test -e /etc/gai.conf; then \
    sudo grep -q 'precedence :ffff:0:0/96' /etc/gai.conf 2>/dev/null || \
      echo 'precedence :ffff:0:0/96  100' | sudo tee -a /etc/gai.conf >/dev/null || true; \
  fi; \
  if ! docker image inspect python:3.12-slim >/dev/null 2>&1; then \
    if docker image inspect distinct-news-bot:latest >/dev/null 2>&1; then \
      echo 'python:3.12-slim missing; using distinct-news-bot:latest as local build base'; \
      docker tag distinct-news-bot:latest python:3.12-slim; \
    fi; \
  fi; \
  if docker compose build --pull=false; then \
    docker compose up -d --remove-orphans; \
  else \
    echo 'Local-cache build failed; retrying with registry pull…' >&2; \
    docker compose build --pull=true && docker compose up -d --remove-orphans; \
  fi && docker compose ps"

echo "==> Publishing dashboard on ports 80 and 443 via nginx"
ssh_cmd "sudo bash $(printf %q "$DEPLOY_PATH")/deploy/setup-dashboard-nginx.sh $(printf %q "$DEPLOY_PATH") 8080 || \
  bash $(printf %q "$DEPLOY_PATH")/deploy/setup-dashboard-nginx.sh $(printf %q "$DEPLOY_PATH") 8080"

echo "==> Opening dashboard ports 80 and 443 on server firewall"
ssh_cmd "sudo bash $(printf %q "$DEPLOY_PATH")/deploy/open-dashboard-port.sh 80 || bash $(printf %q "$DEPLOY_PATH")/deploy/open-dashboard-port.sh 80 || true"
ssh_cmd "sudo bash $(printf %q "$DEPLOY_PATH")/deploy/open-dashboard-port.sh 443 || bash $(printf %q "$DEPLOY_PATH")/deploy/open-dashboard-port.sh 443 || true"

echo "==> Waiting for bot to finish Telegram bootstrap"
ssh_cmd "sleep 15"

echo "==> Recent logs"
ssh_cmd "cd $(printf %q "$DEPLOY_PATH") && \
  docker inspect distinct-news-bot --format 'restarts={{.RestartCount}} status={{.State.Status}}' && \
  docker compose logs --tail=80 bot"

echo "==> Dashboard status"
ssh_cmd "cd $(printf %q "$DEPLOY_PATH") && docker compose ps dashboard && \
  (curl -kfsS https://127.0.0.1/health && echo) || \
  (curl -fsS http://127.0.0.1:8080/health && echo) || echo 'dashboard health check failed'"

echo "==> Deploy finished"
