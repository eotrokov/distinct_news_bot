#!/usr/bin/env bash
# Publish dashboard on host port 443 via nginx reverse proxy.
set -euo pipefail

APP_DIR="${1:-/opt/distinct-news-bot}"
UPSTREAM_PORT="${2:-8080}"
PUBLIC_PORT="${3:-443}"

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n "$@" 2>/dev/null || sudo "$@"
  else
    "$@"
  fi
}

if ! command -v nginx >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  run_root apt-get update -qq
  run_root apt-get install -y -qq nginx openssl
fi

SSL_DIR="/etc/nginx/ssl"
SSL_CERT="${SSL_DIR}/distinct-news-dashboard.crt"
SSL_KEY="${SSL_DIR}/distinct-news-dashboard.key"
run_root mkdir -p "$SSL_DIR"
if [[ ! -f "$SSL_CERT" ]]; then
  run_root openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$SSL_KEY" \
    -out "$SSL_CERT" \
    -subj "/CN=distinct-news-dashboard"
fi

run_root cp "${APP_DIR}/deploy/nginx-dashboard.conf" \
  /etc/nginx/sites-available/distinct-news-dashboard
run_root ln -sf /etc/nginx/sites-available/distinct-news-dashboard \
  /etc/nginx/sites-enabled/distinct-news-dashboard

if [[ -e /etc/nginx/sites-enabled/default ]]; then
  run_root mv /etc/nginx/sites-enabled/default \
    /etc/nginx/sites-enabled/default.disabled-by-distinct-news-bot
fi

run_root nginx -t
run_root systemctl enable nginx
run_root systemctl reload nginx

echo "nginx: dashboard proxied on port ${PUBLIC_PORT} -> 127.0.0.1:${UPSTREAM_PORT}"
