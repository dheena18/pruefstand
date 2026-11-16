#!/usr/bin/env bash
# runner-env-names.sh [file] (D1267): print the variable NAMES of the runner's env file, never a value.
# Owner, on the VM (the script is read from stdin, so user pruefstand needs no access to the checkout):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-names.sh
# A name is printed only for a line that starts an assignment (`NAME=` or `export NAME=` at the line
# start) while no value is open: "NAME" or "NAME (empty)". Continuation lines of a value are never
# printed; comments and blank lines are skipped; any other line is reported by its number only.
# Exit: 0 ok, 2 no such file or a line longer than 8192 bytes (refused, nothing judged).
set -euo pipefail
set +x  # a trace would show the lines
export LC_ALL=C

file="${1:-/home/pruefstand/runner.env}"
[ -f "$file" ] || { echo "runner-env-names: no such file: $file" >&2; exit 2; }

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

st=""
number=0
while IFS= read -r line || [ -n "$line" ]; do
  number=$((number + 1))
  if [ "${#line}" -gt "$MAX_LINE" ]; then
    echo "runner-env-names: line $number is longer than $MAX_LINE bytes: refused" >&2
    exit 2
  fi
  if [ -n "$st" ]; then
    continue_value "$line"
    continue
  fi
  trimmed="${line#"${line%%[![:space:]]*}"}"
  case "$trimmed" in "" | "#"*) continue ;; esac
  if ! [[ "$line" =~ $ASSIGN ]]; then
    echo "line $number: skipped (not NAME=value)"
    continue
  fi
  name="${BASH_REMATCH[2]}"
  start_value "${BASH_REMATCH[3]}"
  if [ -z "$st" ] && is_blank; then echo "$name (empty)"; else echo "$name"; fi
done < "$file"
