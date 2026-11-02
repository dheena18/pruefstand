#!/usr/bin/env bash
# Start the ONE Ollama server on the cluster, only if none answers (ADR-0018, ADR-0019, D228, Y5.4).
#
# usage: start-ollama.sh            (no arguments; there is no mode, a server never starts per mode)
#   1. a server that answers /api/tags on $OLLAMA_HOST is REUSED: nothing is started, exit 0;
#   2. an "ollama serve" process that does not answer yet is never joined by a second one: exit 1;
#   3. otherwise the owner's start script of record runs detached, exactly once:
#        setsid nohup "$OLLAMA_START_SCRIPT" > "$OLLAMA_LOG" 2>&1 < /dev/null &
#      (never tmux, never an own `ollama serve` with an own environment, no pid file).
# Exit: 0 running or started, 1 start script missing / a server process exists but does not answer /
# cluster.env missing or malformed, 2 usage. The VM waits for /api/tags (health.sh --repair, <= 5 min).
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"

if [ "$#" -ne 0 ]; then
  echo "usage: start-ollama.sh   (no arguments; the old mode argument is gone, ADR-0018)" >&2
  exit 2
fi
load_cluster_env "$BIN/cluster.env"

if curl -sf --max-time 5 "$(api_url)/api/tags" >/dev/null 2>&1; then
  echo "an Ollama server already answers on $OLLAMA_HOST; nothing started"
  exit 0
fi
existing="$(serve_pids | tr '\n' ' ')"
[ -z "${existing// /}" ] || die "an ollama serve process (pid ${existing}) exists but does not answer; not starting a second server" 1
[ -x "$OLLAMA_START_SCRIPT" ] || die "the owner's start script $OLLAMA_START_SCRIPT is missing or not executable; nothing started" 1

setsid nohup "$OLLAMA_START_SCRIPT" >"$OLLAMA_LOG" 2>&1 </dev/null &
echo "started $OLLAMA_START_SCRIPT detached; the server needs a moment to answer on $OLLAMA_HOST"
