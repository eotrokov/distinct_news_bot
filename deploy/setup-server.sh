#!/usr/bin/env bash
# First-time helpers on a Linux VPS where Docker already runs other bots.
# Usage (on the server):
#   sudo bash deploy/setup-server.sh [/opt/distinct-news-bot]

set -euo pipefail

APP_DIR="${1:-/opt/distinct-news-bot}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 $APP_DIR" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl git rsync

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

systemctl enable --now docker

if [[ -f "$(dirname "$0")/open-dashboard-port.sh" ]]; then
  bash "$(dirname "$0")/open-dashboard-port.sh" 443 || true
fi

mkdir -p "$APP_DIR/data"
chmod 750 "$APP_DIR"

echo
echo "Server ready for distinct-news-bot at $APP_DIR"
echo "Next:"
echo "  1. Copy project into $APP_DIR (or run deploy/deploy.sh from your machine)"
echo "  2. Create $APP_DIR/.env from deploy/env.production.example"
echo "  3. cd $APP_DIR && docker compose up -d --build"
echo "  4. docker compose logs -f bot"
echo
echo "Existing bots are left untouched — this uses its own container and volume."
