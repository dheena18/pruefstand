#!/usr/bin/env bash
# Runs `make check` at most PRUEFSTAND_CHECK_SLOTS (default 2) at a time on this machine.
#
# Several task agents share the VM; a full `make check` takes minutes of CPU and load-sensitive
# tests fail when more than two run at once (timing). Each run takes one slot lock under
# ~/.cache/pruefstand-check (flock, released when the run ends or is killed); a third run waits
# for a free slot. Targeted tests (`uv run pytest <path>`) do not need a slot: use them while you
# work and this script only before you push. Usage: scripts/vm_check.sh [make args]
set -u
slots="${PRUEFSTAND_CHECK_SLOTS:-2}"
dir="${PRUEFSTAND_CHECK_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/pruefstand-check}"
mkdir -p "$dir"
waited=0
while true; do
  for ((i = 1; i <= slots; i++)); do
    exec {fd}>"$dir/slot$i.lock"
    if flock -n "$fd"; then
      [ "$waited" -eq 0 ] || echo "vm_check: slot $i free after ${waited}s" >&2
      make check "$@"
      exit $?
    fi
    exec {fd}>&-
  done
  [ "$waited" -ne 0 ] || echo "vm_check: all $slots check slots busy, waiting" >&2
  sleep 3
  waited=$((waited + 3))
done
