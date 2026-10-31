#!/usr/bin/env bash
# install-tunnel.sh: install (or replace) the SYSTEM unit pruefstand-tunnel.service (S5, D242, ADR-0018).
#
# Run once by the owner: sudo infra/vm/install-tunnel.sh [--dry-run]   (idempotent)
# Replaces the first unit of setup log section 3 (127.0.0.1 forward only) with the repo unit, which also
# forwards 172.17.0.1:11434 for llm-proxy. Needs Docker running (docker0 must have 172.17.0.1) and autossh.
# When the unit file changed, the tunnel is restarted once (an active tunnel keeps its old forwards otherwise).
# This is a system unit owned by the system and run as user pruefstand (Y1.1), never a per-user unit.
#   --unit-dir DIR   target directory (default /etc/systemd/system; tests only)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT=pruefstand-tunnel.service
UNIT_DIR=/etc/systemd/system
DRY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --unit-dir) UNIT_DIR="$2"; shift 2 ;;
    -h | --help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY" -eq 1 ]; then echo "PLAN $*"; else echo "DO   $*"; "$@"; fi
}

if [ "$DRY" -eq 0 ]; then
  [ "$(id -u)" -eq 0 ] || { echo "install-tunnel: needs root (sudo), or use --dry-run" >&2; exit 2; }
  command -v autossh >/dev/null || { echo "install-tunnel: autossh missing (apt install autossh)" >&2; exit 3; }
  if ! ip -4 addr show docker0 2>/dev/null | grep -q '172\.17\.0\.1'; then
    echo "install-tunnel: docker0 has no 172.17.0.1; start Docker first (the second forward binds it)" >&2
    exit 3
  fi
fi

if cmp -s "$HERE/$UNIT" "$UNIT_DIR/$UNIT" 2>/dev/null; then
  echo "OK   $UNIT_DIR/$UNIT is up to date"
  run systemctl enable --now pruefstand-tunnel
else
  run install -m 0644 -o root -g root "$HERE/$UNIT" "$UNIT_DIR/$UNIT"
  run systemctl daemon-reload
  run systemctl enable pruefstand-tunnel
  run systemctl restart pruefstand-tunnel
fi
