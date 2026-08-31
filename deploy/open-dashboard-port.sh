#!/usr/bin/env bash
# Open dashboard port on common Linux firewalls (best-effort).
set -euo pipefail

PORT="${1:-8080}"

if command -v ufw >/dev/null 2>&1; then
  if ufw status 2>/dev/null | grep -qi "Status: active"; then
    ufw allow "${PORT}/tcp" comment "distinct-news-dashboard" >/dev/null || true
    echo "ufw: allowed ${PORT}/tcp"
  else
    echo "ufw: installed but inactive, skipped"
  fi
fi

if command -v firewall-cmd >/dev/null 2>&1; then
  if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null || true
    firewall-cmd --reload >/dev/null || true
    echo "firewalld: allowed ${PORT}/tcp"
  fi
fi

if command -v iptables >/dev/null 2>&1; then
  if ! iptables -C INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null || true
    echo "iptables: added rule for ${PORT}/tcp"
  fi
fi
