#!/usr/bin/env bash
# setup-data-root.sh: create the data root and its top-level directories (ADR-0019, setup log section 6).
#
# The data root is a PLAIN DIRECTORY on the VM disk: no NFS share, no mount unit, and /etc/fstab is never
# touched. Idempotent: existing directories, owners and content are kept; only what differs is changed.
#   --root DIR      data root (default /mnt/pruefstand)
#   --owner U:G     owner of the directories (default pruefstand:pruefstand)
#   --dry-run       print what would change ("PLAN ..."), change nothing
# Run once by the owner with sudo.
set -euo pipefail

ROOT=/mnt/pruefstand
OWNER=pruefstand:pruefstand
DRY=0
MIN_FREE_KB=$((20 * 1024 * 1024))
SENTINEL=.pruefstand-data-root
DIRS=(data corpus datasets baselines backups cache logs)
changes=0

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

run() {
  changes=$((changes + 1))
  if [ "$DRY" -eq 1 ]; then
    echo "PLAN $*"
  else
    echo "DO   $*"
    "$@"
  fi
}

die() { echo "setup-data-root: $*" >&2; exit 3; }

# ensure_dir PATH: directory exists, owned by OWNER, mode 2775 (setgid, group-writable).
ensure_dir() {
  local path="$1"
  [ ! -L "$path" ] || die "$path is a symlink; refusing to follow it (ADR-0019: plain directories only)"
  [ -d "$path" ] || run mkdir -p "$path"
  if [ -d "$path" ]; then
    [ "$(stat -c '%U:%G' "$path")" = "$OWNER" ] || run chown -h "$OWNER" "$path"
    [ "$(stat -c '%a' "$path")" = 2775 ] || run chmod 2775 "$path"
  else
    # dry run on a missing directory: the owner and mode steps are still part of the plan
    run chown -h "$OWNER" "$path"
    run chmod 2775 "$path"
  fi
}

ensure_dir "$ROOT"
for name in "${DIRS[@]}"; do
  ensure_dir "$ROOT/$name"
done

[ ! -L "$ROOT/$SENTINEL" ] || die "$ROOT/$SENTINEL is a symlink"
if [ ! -e "$ROOT/$SENTINEL" ]; then
  run install -m 0664 -o "${OWNER%%:*}" -g "${OWNER##*:}" /dev/null "$ROOT/$SENTINEL"
fi

if [ -d "$ROOT" ]; then
  if mountpoint -q "$ROOT" 2>/dev/null; then
    echo "WARN $ROOT is a mount point; ADR-0019 wants a plain directory on the VM disk"
  fi
  free_kb="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
  if [ "${free_kb:-0}" -lt "$MIN_FREE_KB" ]; then
    echo "WARN only $((free_kb / 1024 / 1024)) GiB free under $ROOT (need >= 20 GiB, else preflight reports data_root_unavailable)"
  else
    echo "OK   $((free_kb / 1024 / 1024)) GiB free under $ROOT"
  fi
fi

if [ "$changes" -eq 0 ]; then
  echo "no changes needed for $ROOT"
fi
