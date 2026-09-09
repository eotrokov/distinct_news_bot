#!/usr/bin/env bash
# Restore host nginx config that was displaced by the dashboard proxy on 80/443.
set -euo pipefail

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
  echo "nginx is not installed, nothing to restore"
  exit 0
fi

SITES_BACKUP="/etc/nginx/sites-enabled.distinct-news-bot-backup"
CONF_BACKUP="/etc/nginx/conf.d.distinct-news-bot-backup"

run_root rm -f /etc/nginx/sites-enabled/distinct-news-dashboard
run_root rm -f /etc/nginx/sites-available/distinct-news-dashboard

if [[ -d "$SITES_BACKUP" ]]; then
  shopt -s nullglob
  for site in "$SITES_BACKUP"/*; do
    base="$(basename "$site")"
    run_root ln -sf "$site" "/etc/nginx/sites-enabled/${base}"
  done
  shopt -u nullglob
fi

if [[ -d "$CONF_BACKUP" ]]; then
  shopt -s nullglob
  for conf in "$CONF_BACKUP"/*.conf; do
    base="$(basename "$conf")"
    run_root mv "$conf" "/etc/nginx/conf.d/${base}"
  done
  shopt -u nullglob
fi

if ! run_root nginx -t; then
  echo "nginx config test failed after restore" >&2
  exit 1
fi

run_root systemctl enable nginx
run_root systemctl restart nginx

echo "nginx: restored previous proxy on ports 80/443"
