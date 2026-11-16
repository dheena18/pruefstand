#!/usr/bin/env bash
# runner-env-names.sh [file] (D1267): print the variable NAMES of the runner's env file, never a value.
# Owner, on the VM (the script is read from stdin, so user pruefstand needs no access to the checkout):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-names.sh
# A name is printed only for a line that starts a new assignment (`NAME=` or `export NAME=` at the line
# start, outside any open quoted value): "NAME" or "NAME (empty)". Continuation lines of a multi-line value
# (open "..." with \" escapes, open '...', trailing backslash) are never printed; comments and blank lines
# are skipped; any other line is reported by its number only. Exit: 0 ok, 2 no such file.
set -euo pipefail
set +x  # a trace would show the lines

file="${1:-/home/pruefstand/runner.env}"
[ -f "$file" ] || { echo "runner-env-names: no such file: $file" >&2; exit 2; }

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

st=""
number=0
while IFS= read -r line || [ -n "$line" ]; do
  number=$((number + 1))
  if [ -n "$st" ]; then
    scan "$line"
    continue
  fi
  trimmed="${line#"${line%%[![:space:]]*}"}"
  case "$trimmed" in "" | "#"*) continue ;; esac
  if ! [[ "$line" =~ $ASSIGN ]]; then
    echo "line $number: skipped (not NAME=value)"
    scan "$line"
    continue
  fi
  name="${BASH_REMATCH[2]}"
  value="${BASH_REMATCH[3]}"
  scan "$value"
  if [ -z "$st" ] && is_blank "$value"; then echo "$name (empty)"; else echo "$name"; fi
done < "$file"
