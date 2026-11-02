#!/usr/bin/env bash
# Stop the ONE Ollama server (only via pruefstand-cluster under the GPU lock; normally the owner restarts it, runbook 2a).
#
# Before a signal is sent the pid is checked twice (A12-M3): its /proc/<pid>/cmdline is `ollama serve`, and that
# very pid listens on the Ollama port. Anything else is reported and nothing is killed. No pid file exists.
# STOP_WAIT_S (default 60): seconds to wait for the process to disappear; 0 = signal only.
# Exit: 0 stopped / signalled / nothing running, 1 refused or still running, 2 usage.
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"

[ "$#" -eq 0 ] || {
  echo "usage: stop-ollama.sh   (no arguments)" >&2
  exit 2
}
load_cluster_env "$BIN/cluster.env"

mapfile -t serve < <(serve_pids)
if [ "${#serve[@]}" -eq 0 ]; then
  others="$(pgrep_pids | tr '\n' ' ')"
  [ -z "${others// /}" ] || die "pid ${others}found by pgrep is not ollama serve; nothing killed" 1
  echo "no ollama process; nothing to stop"
  exit 0
fi
[ "${#serve[@]}" -eq 1 ] || die "more than one ollama serve process (${serve[*]}); refusing to guess, nothing killed" 1
pid="${serve[0]}"
mapfile -t listeners < <(listener_pids)
printf '%s\n' "${listeners[@]}" | grep -qx "$pid" || die "pid $pid is ollama serve but does not listen on $OLLAMA_HOST; nothing killed" 1

env kill -TERM "$pid"
waited=0
while [ "$waited" -lt "${STOP_WAIT_S:-60}" ] && [ -d "$PROC/$pid" ]; do
  sleep 1
  waited=$((waited + 1))
done
if [ "${STOP_WAIT_S:-60}" -gt 0 ] && [ -d "$PROC/$pid" ]; then
  die "pid $pid still running after ${STOP_WAIT_S:-60}s" 1
fi
echo "ollama serve (pid $pid) stopped"
