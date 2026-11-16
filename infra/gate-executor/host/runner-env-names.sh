#!/usr/bin/env bash
# runner-env-names.sh [file] (D1267): print the variable NAMES of the runner's env file, never a value.
# Owner, on the VM (the script is read from stdin, so user pruefstand needs no access to the checkout):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-names.sh
# Accepts NAME=value and `export NAME=value`; prints "NAME (empty)" for an empty value, skips comments and
# blank lines, reports other lines only by number, and skips the continuation lines of a quoted multi-line
# value. Exit: 0 ok, 2 no such file.
set -euo pipefail
set +x  # a trace would show the lines

file="${1:-/home/pruefstand/runner.env}"
[ -f "$file" ] || { echo "runner-env-names: no such file: $file" >&2; exit 2; }

number=0
open_quote=""
while IFS= read -r line || [ -n "$line" ]; do
  number=$((number + 1))
  if [ -n "$open_quote" ]; then
    case "$line" in *"$open_quote"*) open_quote="" ;; esac
    continue
  fi
  trimmed="${line#"${line%%[![:space:]]*}"}"
  case "$trimmed" in "" | "#"*) continue ;; esac
  trimmed="${trimmed#export }"
  name="${trimmed%%=*}"
  if [ "$name" = "$trimmed" ] || ! [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "line $number: skipped (not NAME=value)"
    continue
  fi
  value="${trimmed#*=}"
  for quote in '"' "'"; do
    if [ "${value:0:1}" = "$quote" ]; then
      rest="${value:1}"
      case "$rest" in *"$quote"*) ;; *) open_quote="$quote" ;; esac
    fi
  done
  if [ -z "$value" ]; then echo "$name (empty)"; else echo "$name"; fi
done < "$file"
