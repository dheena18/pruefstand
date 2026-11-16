#!/usr/bin/env bash
# runner-env-keys.sh [file] (D1267): append PRUEFSTAND_NONCE_KEY and PRUEFSTAND_CANDIDATE_API_KEY to the
# runner's env file when they are missing; never prints a value, never changes an existing line.
# Owner, on the VM, as the file's owner (the script is read from stdin):
#   sudo -u pruefstand bash -s -- /home/pruefstand/runner.env < infra/gate-executor/host/runner-env-keys.sh
# Each value is `openssl rand -hex 32` (docs/ops/secrets.md). A missing file is created with mode 0600.
# Refused (exit 2, file unchanged): a symlink, a file readable or writable by group or others, a key that is
# present with an empty value (remove that line by hand, then run again). Exit 0: both keys present.
set -euo pipefail
set +x  # a trace would show the values

file="${1:-/home/pruefstand/runner.env}"
keys=(PRUEFSTAND_NONCE_KEY PRUEFSTAND_CANDIDATE_API_KEY)
die() { echo "runner-env-keys: $1" >&2; exit 2; }

[ ! -L "$file" ] || die "$file is a symlink: refused"
if [ ! -e "$file" ]; then
  (umask 077 && : > "$file")
fi
[ -f "$file" ] || die "$file is not a regular file"
mode="$(stat -c %a "$file")"
[ "$mode" = 600 ] || [ "$mode" = 400 ] || die "$file has mode $mode, expected 600: refused"
[ -O "$file" ] || die "$file is not owned by $(id -un): run as its owner"
command -v openssl >/dev/null || die "openssl is missing"

state() {  # prints: missing | empty | set   (reads names and emptiness only)
  local key="$1" line trimmed
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    trimmed="${trimmed#export }"
    case "$trimmed" in
      "$key=") echo empty; return ;;
      "$key="*) echo set; return ;;
    esac
  done < "$file"
  echo missing
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
