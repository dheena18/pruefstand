#!/usr/bin/env bash
# setup-users.sh: service user, groups, lock directory and lock wrapper of the VM (Y1, D211-D213).
#
# Run once by the owner: sudo infra/vm/setup-users.sh [--dry-run]   (idempotent)
#   * system user + group `pruefstand` (created only if missing; an existing user is kept, its shell is
#     only reported unless --fix-shell is given)
#   * the owner (--owner, default $SUDO_USER) joins group `pruefstand`
#   * group `docker` = exactly `pruefstand` + the owner; any other member is printed and NOT removed
#     unless --force is given (exit 4 when extra members remain)
#   * /var/lib/pruefstand (pruefstand:pruefstand, 2770) and gpu.lock (0660); MAINTENANCE is never created
#   * /usr/local/bin/pruefstand-lock (0755) from infra/vm/pruefstand-lock
# Options: --dry-run  --fix-shell  --force  --owner U  --lock-dir D  --bin-dir D  --home D
# (--lock-dir/--bin-dir/--home exist so tests can use temp dirs; defaults are the production paths.)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SVC=pruefstand
SVC_HOME=/home/pruefstand
OWNER="${SUDO_USER:-}"
LOCK_DIR=/var/lib/pruefstand
BIN_DIR=/usr/local/bin
HOME_DIR=/home/pruefstand
NOLOGIN=/usr/sbin/nologin
DRY=0
FIX_SHELL=0
FORCE=0
rc=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --fix-shell) FIX_SHELL=1; shift ;;
    --force) FORCE=1; shift ;;
    --owner) OWNER="$2"; shift 2 ;;
    --lock-dir) LOCK_DIR="$2"; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --home) HOME_DIR="$2"; shift 2 ;;
    -h | --help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$OWNER" ] || [ "$OWNER" = root ]; then
  echo "setup-users: owner user unknown; run with sudo from the owner's login or pass --owner USER" >&2
  exit 2
fi
if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  echo "setup-users: needs root (sudo), or use --dry-run" >&2
  exit 2
fi

die() { echo "setup-users: $*" >&2; exit 3; }
no_symlink() { [ ! -L "$1" ] || die "$1 is a symlink; refusing to follow it"; }

run() {
  if [ "$DRY" -eq 1 ]; then echo "PLAN $*"; else echo "DO   $*"; "$@"; fi
}

# members_of GROUP: space-separated supplementary members (empty if the group is missing).
members_of() { getent group "$1" 2>/dev/null | cut -d: -f4 | tr ',' ' ' || true; }
has_word() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

ensure_user() {
  local entry
  entry="$(getent passwd "$SVC" || true)"
  if [ -z "$entry" ]; then
    run useradd --system --user-group --create-home --home-dir "$SVC_HOME" --shell "$NOLOGIN" "$SVC"
    return
  fi
  local shell="${entry##*:}"
  if [ "$shell" != "$NOLOGIN" ]; then
    echo "NOTE user $SVC keeps shell $shell (autossh does not need one)"
    if [ "$FIX_SHELL" -eq 1 ]; then
      run usermod --shell "$NOLOGIN" "$SVC"
    else
      echo "NOTE pass --fix-shell to switch it to $NOLOGIN"
    fi
  fi
}

ensure_membership() {
  has_word "$OWNER" "$(members_of "$SVC")" || run usermod -aG "$SVC" "$OWNER"
  if ! getent group docker >/dev/null; then
    echo "setup-users: group docker missing; install Docker first (docker.io + docker-compose-v2)" >&2
    exit 3
  fi
  local current member
  current="$(members_of docker)"
  for member in "$SVC" "$OWNER"; do
    has_word "$member" "$current" || run usermod -aG docker "$member"
  done
  for member in $current; do
    if [ "$member" != "$SVC" ] && [ "$member" != "$OWNER" ]; then
      if [ "$FORCE" -eq 1 ]; then
        run gpasswd -d "$member" docker
      else
        echo "EXTRA docker group member '$member' (only $SVC and $OWNER may be members); not removed, use --force"
        rc=4
      fi
    fi
  done
}

ensure_home_mode() {
  no_symlink "$HOME_DIR"
  if [ -d "$HOME_DIR" ] && [ "$(stat -c '%a' "$HOME_DIR")" != 700 ]; then
    run chmod 0700 "$HOME_DIR"
  fi
}

ensure_lock() {
  local lock="$LOCK_DIR/gpu.lock"
  no_symlink "$LOCK_DIR"
  no_symlink "$lock"
  if [ ! -d "$LOCK_DIR" ]; then
    run install -d -o "$SVC" -g "$SVC" -m 2770 "$LOCK_DIR"
  elif [ "$(stat -c '%a %U:%G' "$LOCK_DIR")" != "2770 $SVC:$SVC" ]; then
    run chown -h "$SVC:$SVC" "$LOCK_DIR"
    run chmod 2770 "$LOCK_DIR"
  fi
  if [ ! -e "$lock" ]; then
    run install -o "$SVC" -g "$SVC" -m 0660 /dev/null "$lock"
    return
  fi
  # Open first, then verify and change through the descriptor. A swap between the check above and the open is
  # caught by comparing device:inode of the descriptor with the path; the descriptor itself cannot be swapped.
  exec 8<"$lock"
  [ ! -L "$lock" ] || die "$lock is a symlink; refusing to follow it"
  [ -f /proc/self/fd/8 ] || die "$lock is not a regular file"
  [ "$(stat -L -c %d:%i /proc/self/fd/8)" = "$(stat -c %d:%i "$lock")" ] ||
    die "$lock changed while it was being opened; run again"
  if [ "$(stat -L -c '%a %U:%G' /proc/self/fd/8)" != "660 $SVC:$SVC" ]; then
    run chown "$SVC:$SVC" /proc/self/fd/8
    run chmod 0660 /proc/self/fd/8
  fi
  exec 8<&-
}

ensure_wrapper() {
  local target="$BIN_DIR/pruefstand-lock"
  if ! cmp -s "$HERE/pruefstand-lock" "$target" 2>/dev/null; then
    run install -m 0755 -o root -g root "$HERE/pruefstand-lock" "$target"
  fi
}

ensure_user
ensure_membership
ensure_home_mode
ensure_lock
ensure_wrapper
echo "note: group changes apply to $OWNER at the next login (log out and in, or: newgrp)"
exit "$rc"
