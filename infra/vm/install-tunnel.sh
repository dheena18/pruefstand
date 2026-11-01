#!/usr/bin/env bash
# install-tunnel.sh: install (or replace) the SYSTEM unit pruefstand-tunnel.service (S5, D242, ADR-0018).
#
# Run once by the owner: sudo infra/vm/install-tunnel.sh [--dry-run]   (idempotent)
# Replaces the first unit of setup log section 3 (127.0.0.1 forward only) with the repo unit, which also
# forwards 172.17.0.1:11434 for llm-proxy. Needs Docker running (docker0 must have 172.17.0.1) and autossh.
# Refuses unless pruefstand-firewall is active and its --check-gateway passes (run setup-proxy-net.sh first). When the unit file changed, the old
# unit is saved as <unit>.bak, the tunnel is restarted once, and if it does not come up with both listeners within
# TUNNEL_WAIT_S (20) seconds the backup is restored and the script exits 1.
# This is a system unit owned by the system and run as user pruefstand (Y1.1), never a per-user unit.
#   --unit-dir DIR      target directory (default /etc/systemd/system; tests only)
#   --firewall-bin F    firewall script to ask (default /usr/local/sbin/pruefstand-firewall.sh; tests only, no env override)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT=pruefstand-tunnel.service
UNIT_DIR=/etc/systemd/system
FIREWALL_BIN=/usr/local/sbin/pruefstand-firewall.sh
COPIED=0
DRY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --unit-dir) UNIT_DIR="$2"; shift 2 ;;
    --firewall-bin) FIREWALL_BIN="$2"; shift 2 ;;
    -h | --help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY" -eq 1 ]; then echo "PLAN $*"; else echo "DO   $*"; "$@"; fi
}
die() { echo "install-tunnel: $*" >&2; exit "${2:-3}"; }

if [ "$DRY" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || die "needs root (sudo), or use --dry-run" 2
  command -v autossh >/dev/null || die "autossh missing (apt install autossh)"
  if ! ip -4 addr show docker0 2>/dev/null | grep -q 'inet 172\.17\.0\.1/'; then
    die "docker0 has no 172.17.0.1; start Docker first (the second forward binds it)"
  fi
  if [ "$(systemctl is-active pruefstand-firewall 2>/dev/null || true)" != active ]; then
    die "pruefstand-firewall is not active; run setup-proxy-net.sh first (the 172.17.0.1 listener needs its drop rule)"
  fi
  "$FIREWALL_BIN" --check-gateway >/dev/null 2>&1 ||
    die "gateway firewall rules are missing or misordered ($FIREWALL_BIN --check-gateway failed); run setup-proxy-net.sh again"
fi

# wait_ready: the unit is active and ssh/autossh listens on both addresses (up to TUNNEL_WAIT_S seconds).
wait_ready() {
  local waited=0 limit="${TUNNEL_WAIT_S:-20}" listen
  while :; do
    listen="$(ss -ltnp 2>/dev/null || true)"
    if [ "$(systemctl is-active pruefstand-tunnel 2>/dev/null || true)" = active ] &&
      grep -E '"(auto)?ssh"' <<<"$listen" | grep -q '127\.0\.0\.1:11434' &&
      grep -E '"(auto)?ssh"' <<<"$listen" | grep -q '172\.17\.0\.1:11434'; then
      return 0
    fi
    [ "$waited" -lt "$limit" ] || return 1
    sleep 1
    waited=$((waited + 1))
  done
}

rollback() {
  local unit="$UNIT_DIR/$UNIT"
  echo "install-tunnel: the new tunnel did not come up with both listeners (127.0.0.1:11434 and 172.17.0.1:11434)" >&2
  if [ "$COPIED" -eq 1 ] && [ -f "$unit.bak" ]; then
    mv "$unit.bak" "$unit"
    systemctl daemon-reload
    systemctl restart pruefstand-tunnel || true
    echo "install-tunnel: restored the previous unit from $unit.bak" >&2
  else
    echo "install-tunnel: nothing to restore from this run; see: journalctl -u pruefstand-tunnel" >&2
  fi
  exit 1
}

if cmp -s "$HERE/$UNIT" "$UNIT_DIR/$UNIT" 2>/dev/null; then
  echo "OK   $UNIT_DIR/$UNIT is up to date"
  run systemctl daemon-reload
  run systemctl enable --now pruefstand-tunnel
  if [ "$DRY" -eq 0 ]; then
    # an interrupted earlier run may have left a changed unit file that systemd has not applied
    if [ "$(systemctl show -p NeedDaemonReload --value pruefstand-tunnel 2>/dev/null || true)" = yes ]; then
      run systemctl restart pruefstand-tunnel
    fi
    wait_ready || rollback
    rm -f "$UNIT_DIR/$UNIT.bak"
    echo "OK   tunnel active with 127.0.0.1:11434 and 172.17.0.1:11434"
  fi
else
  if [ -f "$UNIT_DIR/$UNIT" ]; then
    run rm -f "$UNIT_DIR/$UNIT.bak"
    run cp -p "$UNIT_DIR/$UNIT" "$UNIT_DIR/$UNIT.bak"
    COPIED=1
  fi
  run install -m 0644 "$HERE/$UNIT" "$UNIT_DIR/$UNIT"
  run systemctl daemon-reload
  run systemctl enable pruefstand-tunnel
  if [ "$DRY" -eq 1 ]; then
    echo "PLAN systemctl restart pruefstand-tunnel"
    echo "PLAN wait up to ${TUNNEL_WAIT_S:-20}s for is-active and ssh listeners on both addresses; otherwise restore $UNIT.bak"
  else
    echo "DO   systemctl restart pruefstand-tunnel"
    systemctl restart pruefstand-tunnel || rollback
    wait_ready || rollback
    rm -f "$UNIT_DIR/$UNIT.bak"
    echo "OK   tunnel active with 127.0.0.1:11434 and 172.17.0.1:11434"
  fi
fi
