#!/usr/bin/env bash
# switch-mode.sh day|night [--dry-run]: make the ONE Ollama server hold the mode's models (VM; ADR-0018, ADR-0019).
#
# Runs UNDER the GPU lock (pruefstand-lock; PRUEFSTAND_LOCK_HELD=1) and never takes it itself. API loads and
# unloads only, never a server start/stop/restart for a mode: a server is started (once, through the cluster
# script that reuses a running one) only when none answers. Since ADR-0019 day and night load the same set:
# generator, then bge-m3, then the judge, each with {model, keep_alive, options = the catalogue options}
# (AI12-04, so the first real request does not reload). Catalogue models outside the mode are unloaded first;
# models of other users are reported (WARN) and left alone. It never creates or removes MAINTENANCE.
# Exit: 0 ok, 1 a load failed or no server answers, 2 not under the lock, 64 usage ("datagen": no such mode).
# Env: OLLAMA_GPU0_URL / OLLAMA_GPU1_URL (lane URLs), SERVER_WAIT_S (default 300), LOAD_TIMEOUT_S (default 900).
set -euo pipefail

# shellcheck source=lib/gpu_common.sh
. "$(cd "$(dirname "$0")" && pwd)/lib/gpu_common.sh"
require_lock

mode=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -*) die "usage: switch-mode.sh day|night [--dry-run]" 64 ;;
    *) [ -z "$mode" ] || die "usage: switch-mode.sh day|night [--dry-run]" 64; mode="$arg" ;;
  esac
done
[ -n "$mode" ] || die "usage: switch-mode.sh day|night [--dry-run]" 64
cat_py mode-set "$mode" >/dev/null || exit "$?"

ensure_server "${SERVER_WAIT_S:-300}"
normalise_mode "$mode"
say "mode $mode ready"
