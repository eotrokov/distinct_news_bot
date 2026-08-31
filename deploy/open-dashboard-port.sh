#!/usr/bin/env bash
# Open dashboard port on common Linux firewalls (best-effort).
set -euo pipefail

PORT="${1:-443}"

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n "$@" 2>/dev/null || sudo "$@"
  else
    "$@"
  fi
}

if command -v ufw >/dev/null 2>&1; then
  if run_root ufw status 2>/dev/null | grep -qi "Status: active"; then
    run_root ufw allow "${PORT}/tcp" comment "distinct-news-dashboard" >/dev/null || true
    echo "ufw: allowed ${PORT}/tcp"
  else
    run_root ufw allow "${PORT}/tcp" comment "distinct-news-dashboard" >/dev/null || true
    echo "ufw: allowed ${PORT}/tcp (ufw inactive, rule pre-added)"
  fi
fi

if command -v firewall-cmd >/dev/null 2>&1; then
  if run_root systemctl is-active --quiet firewalld 2>/dev/null; then
    run_root firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null || true
    run_root firewall-cmd --reload >/dev/null || true
    echo "firewalld: allowed ${PORT}/tcp"
  fi
fi

if command -v iptables >/dev/null 2>&1; then
  if ! run_root iptables -C INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null; then
    run_root iptables -I INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null || true
    echo "iptables: added rule for ${PORT}/tcp"
  else
    echo "iptables: rule for ${PORT}/tcp already exists"
  fi
fi
