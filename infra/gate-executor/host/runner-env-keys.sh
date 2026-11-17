#!/usr/bin/env bash
# runner-env-keys.sh [file] (D1267, D1281): append PRUEFSTAND_NONCE_KEY, PRUEFSTAND_CANDIDATE_API_KEY and
# QDRANT_READ_ONLY_API_KEY to the runner's env file when they are missing; never prints a value, never changes
# an existing line.
# Owner, on the VM, as the file's owner (the script is read from stdin):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-keys.sh
# Each value is `openssl rand -hex 32` (docs/ops/secrets.md), written straight from openssl into the file.
# A missing file is created with mode 0600. Refused (exit 2, file unchanged): a symlink, a file owned by
# another user or not writable, a mode other than 600, a line longer than 8192 bytes, a key present with an
# empty value (empty, blank, "" or '', also before a trailing comment): remove that line by hand, then run
# again. Only lines that start an assignment count, never a line inside an open value. Exit 0: all keys
# present.
set -euo pipefail
set +x  # a trace would show the values
export LC_ALL=C

file="${1:-/home/pruefstand/runner.env}"
# QDRANT_READ_ONLY_API_KEY: the executor Qdrant's read-only key (compose.executor.yml), the only Qdrant key the
# candidate gets, as its QDRANT_API_KEY (D1098).
keys=(PRUEFSTAND_NONCE_KEY PRUEFSTAND_CANDIDATE_API_KEY QDRANT_READ_ONLY_API_KEY)
die() { echo "runner-env-keys: $1" >&2; exit 2; }

# --- quote scanner (same code in runner-env-names.sh and runner-env-keys.sh, checked by a test; the
# scripts run from stdin, so they cannot source a shared file). Rules, as for a systemd EnvironmentFile:
# a value that STARTS with " , ' or $' is quoted ("..." and $'...' honour backslash escapes, '...' does
# not) and may span lines; adjacent quoted parts continue it; text after the closing quote is ignored.
# Any other value is unquoted: it ends at the end of the line (quotes inside it are literal), an unquoted
# comment starts at whitespace + '#', and a trailing backslash continues it on the next line.
# State in $st: "" (no open value), dq, sq, ansi (open quoted value), cont (backslash continuation).
# $content is the text of a value that ended on its line; it is only tested for blankness, never shown.
MAX_LINE=8192
close_quoted() {  # $1 text, $2 start index; st is dq|sq|ansi; sets st ("" when closed) and pos
  local s="$1" i="$2" n=${#1} c
  while [ "$i" -lt "$n" ]; do
    c="${s:i:1}"
    if [ "$st" != sq ] && [ "$c" = "\\" ]; then
      i=$((i + 2))
      continue
    fi
    if { [ "$st" = dq ] && [ "$c" = '"' ]; } || { [ "$st" != dq ] && [ "$c" = "'" ]; }; then
      st=""
      pos=$((i + 1))
      return 0
    fi
    content+="$c"
    i=$((i + 1))
  done
  pos=$n
}
unquoted() {  # $1 text of an unquoted value (or its continuation line)
  local s=" $1" tail
  s="${s%%[[:space:]]#*}"
  s="${s# }"
  s="${s%"${s##*[![:space:]]}"}"
  tail="${s##*[!\\]}"
  [ "$s" = "$tail" ] && tail="$s"
  if [ $(( ${#tail} % 2 )) -eq 1 ]; then st=cont; else st=""; fi
  content+="$s"
}
start_value() {  # $1 the text after NAME=
  local s="$1"
  content=""
  st=""
  s="${s#"${s%%[![:space:]]*}"}"
  while :; do
    case "$s" in
      "\$'"*) st=ansi; close_quoted "$s" 2 ;;
      '"'*) st=dq; close_quoted "$s" 1 ;;
      "'"*) st=sq; close_quoted "$s" 1 ;;
      *) unquoted "$s"; return 0 ;;
    esac
    [ -z "$st" ] || return 0
    s="${s:pos}"
    case "$s" in '"'* | "'"* | "\$'"*) ;; *) return 0 ;; esac
  done
}
continue_value() {  # $1 a line read while a value is open
  local s="$1"
  case "$st" in
    cont) st=""; unquoted "$s" ;;
    *)
      close_quoted "$s" 0
      if [ -z "$st" ]; then
        s="${s:pos}"
        case "$s" in '"'* | "'"* | "\$'"*) start_value "$s" ;; esac
      fi ;;
  esac
}
is_blank() {  # $content is empty or whitespace only
  [ -z "${content//[[:space:]]/}" ]
}
ASSIGN='^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$'
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

state() {  # prints missing | empty | set for key $1 (names and blankness only), or fails on a long line
  local key="$1" line result="missing" number=0
  st=""
  while IFS= read -r line || [ -n "$line" ]; do
    number=$((number + 1))
    [ "${#line}" -le "$MAX_LINE" ] || { echo "toolong:$number"; return 0; }
    if [ -n "$st" ]; then
      continue_value "$line"
      continue
    fi
    [[ "$line" =~ $ASSIGN ]] || continue
    local name="${BASH_REMATCH[2]}"
    start_value "${BASH_REMATCH[3]}"
    if [ "$name" = "$key" ]; then
      if [ -z "$st" ] && is_blank; then result="empty"; else result="set"; fi
    fi
  done < "$file"
  echo "$result"
}

for key in "${keys[@]}"; do
  found="$(state "$key")"
  case "$found" in
    toolong:*) die "line ${found#toolong:} is longer than $MAX_LINE bytes: refused" ;;
    empty) die "$key is present with an empty value: remove that line, then run again" ;;
  esac
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
