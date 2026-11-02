#!/usr/bin/env bash
# unload-all.sh [--dry-run]: unload every resident catalogue model; the server keeps running (make gpu-down; ADR-0018).
#
# Under the GPU lock like the other VM scripts (exit 2 without PRUEFSTAND_LOCK_HELD=1). Models of other users are
# reported (WARN) and left alone. Exit: 0 ok (also when no server answers: nothing is loaded), 1 an unload
# failed, 2 not under the lock, 64 usage.
set -euo pipefail

# shellcheck source=lib/gpu_common.sh
. "$(cd "$(dirname "$0")" && pwd)/lib/gpu_common.sh"
require_lock
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    *) die "usage: unload-all.sh [--dry-run]" 64 ;;
  esac
done

declare -A known=()
while IFS= read -r tag; do known["$tag"]=1; done < <(cat_py catalogue-tags)
found=0
while IFS=$'\t' read -r url name _digest _ctx _size _vram; do
  [ -n "$name" ] || continue
  found=1
  if [ -n "${known[$name]:-}" ]; then
    unload_model "$name" "$url"
  else
    warn "$name is resident but not a catalogue model; left alone"
  fi
done < <(residents)
[ "$found" -eq 1 ] || say "no model is resident (or no server answers); nothing to unload"
