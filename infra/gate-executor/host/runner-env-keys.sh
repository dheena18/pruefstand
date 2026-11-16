#!/usr/bin/env bash
# runner-env-keys.sh [file] (D1267): append PRUEFSTAND_NONCE_KEY and PRUEFSTAND_CANDIDATE_API_KEY to the
# runner's env file when they are missing; never prints a value, never changes an existing line.
# Owner, on the VM, as the file's owner (the script is read from stdin):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-keys.sh
# Each value is `openssl rand -hex 32` (docs/ops/secrets.md), written straight from openssl into the file.
# A missing file is created with mode 0600. Refused (exit 2, file unchanged): a symlink, a mode other than
# 600, a file owned by another user or not writable, a key present with an empty, blank or empty-quoted
# value (remove that line by hand, then run again). Only lines that start an assignment count; a key-like
# line inside a quoted multi-line value does not. Exit 0: both keys present.
set -euo pipefail
set +x  # a trace would show the values

file="${1:-/home/pruefstand/runner.env}"
keys=(PRUEFSTAND_NONCE_KEY PRUEFSTAND_CANDIDATE_API_KEY)
die() { echo "runner-env-keys: $1" >&2; exit 2; }

# --- quote scanner (same code in runner-env-names.sh and runner-env-keys.sh; the scripts run from stdin,
# so they cannot source a shared file). scan TEXT: continues the state in $st ("" = between assignments
# or inside an unquoted value, dq = inside "...", sq = inside '...', cont = after a trailing backslash)
# and leaves the state after TEXT in $st. A line read while $st is not "" is a continuation of a value.
scan() {
  local s="$1" i=0 n=${#1} c prev=" "
  [ "$st" = cont ] && st=""
  while [ "$i" -lt "$n" ]; do
    c="${s:i:1}"
    case "$st" in
      sq) [ "$c" = "'" ] && st="" ;;
      dq)
        if [ "$c" = "\\" ]; then
          i=$((i + 1))
          [ "$i" -lt "$n" ] || return 0
        elif [ "$c" = '"' ]; then
          st=""
        fi ;;
      *)
        if [ "$c" = "\\" ]; then
          i=$((i + 1))
          [ "$i" -lt "$n" ] || { st=cont; return 0; }
        elif [ "$c" = '"' ]; then
          st=dq
        elif [ "$c" = "'" ]; then
          st=sq
        elif [ "$c" = "#" ] && { [ "$prev" = " " ] || [ "$prev" = $'\t' ]; }; then
          return 0
        fi ;;
    esac
    prev="$c"
    i=$((i + 1))
  done
}
ASSIGN='^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$'
# blank VALUE: only spaces, or an empty quoted string ("" or '') with optional spaces around
is_blank() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  case "$v" in "" | '""' | "''") return 0 ;; *) return 1 ;; esac
}
# --- end of quote scanner

[ ! -L "$file" ] || die "$file is a symlink: refused"
if [ ! -e "$file" ]; then
  (umask 077 && : > "$file")
fi
[ -f "$file" ] || die "$file is not a regular file"
[ -O "$file" ] || die "$file is not owned by $(id -un): run as its owner"
[ -w "$file" ] || die "$file is not writable (mode $(stat -c %a "$file")): chmod 600 it, then run again"
mode="$(stat -c %a "$file")"
[ "$mode" = 600 ] || die "$file has mode $mode, expected 600: refused"
command -v openssl >/dev/null || die "openssl is missing"

state() {  # prints missing | empty | set for key $1 (reads names and blankness only)
  local key="$1" line result=missing
  st=""
  while IFS= read -r line || [ -n "$line" ]; do
    if [ -n "$st" ]; then
      scan "$line"
      continue
    fi
    if [[ "$line" =~ $ASSIGN ]]; then
      local name="${BASH_REMATCH[2]}" value="${BASH_REMATCH[3]}"
      scan "$value"
      if [ "$name" = "$key" ]; then
        if [ -z "$st" ] && is_blank "$value"; then result="empty"; else result="set"; fi
      fi
    else
      scan "$line"
    fi
  done < "$file"
  echo "$result"
}

for key in "${keys[@]}"; do
  [ "$(state "$key")" != empty ] || die "$key is present with an empty value: remove that line, then run again"
done
for key in "${keys[@]}"; do
  if [ "$(state "$key")" = set ]; then
    echo "$key: present, kept"
    continue
  fi
  if [ -s "$file" ] && [ -n "$(tail -c 1 "$file")" ]; then
    printf '\n' >> "$file"
  fi
  { printf '%s=' "$key"; openssl rand -hex 32; } >> "$file"
  echo "$key: added"
done
chmod 600 "$file"
