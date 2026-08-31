#!/usr/bin/env bash
# Publish dashboard on host ports 80/443 via nginx reverse proxy.
set -euo pipefail

APP_DIR="${1:-/opt/distinct-news-bot}"
UPSTREAM_PORT="${2:-8080}"

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

# Stop docker containers that may hold port 443 from failed deploys.
if command -v docker >/dev/null 2>&1; then
  while read -r name; do
    [[ -z "$name" ]] && continue
    if docker port "$name" 2>/dev/null | grep -q ':443'; then
      echo "Stopping container holding port 443: $name"
      docker stop "$name" >/dev/null || true
    fi
  done < <(docker ps --format '{{.Names}}' 2>/dev/null || true)
fi

# Free port 443 if a non-nginx process is listening.
if command -v ss >/dev/null 2>&1; then
  LISTENER="$(ss -tlnp 2>/dev/null | grep ':443 ' || true)"
  if [[ -n "$LISTENER" ]] && ! echo "$LISTENER" | grep -q nginx; then
    echo "Freeing port 443 from non-nginx listener"
    run_root fuser -k 443/tcp >/dev/null 2>&1 || true
    sleep 1
  fi
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

BACKUP_DIR="/etc/nginx/sites-enabled.distinct-news-bot-backup"
run_root mkdir -p "$BACKUP_DIR"
for site in /etc/nginx/sites-enabled/*; do
  [[ -e "$site" ]] || continue
  base="$(basename "$site")"
  if [[ "$base" != "distinct-news-dashboard" ]]; then
    run_root mv "$site" "${BACKUP_DIR}/${base}" 2>/dev/null || true
  fi
done

run_root cp "${APP_DIR}/deploy/nginx-dashboard.conf" \
  /etc/nginx/sites-available/distinct-news-dashboard
run_root ln -sf /etc/nginx/sites-available/distinct-news-dashboard \
  /etc/nginx/sites-enabled/distinct-news-dashboard

run_root nginx -t
run_root systemctl enable nginx
run_root systemctl restart nginx

echo "nginx: dashboard proxied on ports 80 and 443 -> 127.0.0.1:${UPSTREAM_PORT}"
