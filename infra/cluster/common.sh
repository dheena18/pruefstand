#!/usr/bin/env bash
# Shared helpers of the cluster scripts (sourced, never run). T3.1a, ADR-0018/0019.
#
# A script sets BIN="$(cd "$(dirname "$0")" && pwd)" (the VM's environment is not forwarded over SSH), sources
# this file and calls load_cluster_env "$BIN/cluster.env". Nothing here writes anywhere.
# PRUEFSTAND_PROC_ROOT (default /proc) is a test seam.

# shellcheck disable=SC2034  # variables are used by the scripts that source this file
PROC="${PRUEFSTAND_PROC_ROOT:-/proc}"
NON_SERVER_KEYS=" OLLAMA_START_SCRIPT OLLAMA_LOG MODELS_MIN_FREE_GB GENERATOR_TAG "
ENV_KEYS=()

die() { # message [exit code]
  echo "$(basename "$0"): $1" >&2
  exit "${2:-1}"
}

# Read KEY=VALUE lines of cluster.env WITHOUT executing it: every line must match the strict pattern, a value
# may start with $HOME. A malformed line stops the script (a file that is sourced as code could run anything).
load_cluster_env() { # path
  local file="$1" line key val re
  [ -r "$file" ] || die "cluster.env missing next to the scripts ($file); run deploy-cluster-bin.sh" 1
  # shellcheck disable=SC2016  # the \$ is literal: a value may start with the text \$HOME
  re='^([A-Z][A-Z0-9_]*)=(\$HOME)?([A-Za-z0-9_./:,@%+=-]*)$'
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in '' | '#'*) continue ;; esac
    [[ $line =~ $re ]] || die "cluster.env: refused line (only KEY=VALUE with a plain value is allowed)" 1
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[3]}"
    [ -z "${BASH_REMATCH[2]}" ] || val="$HOME$val"
    printf -v "$key" '%s' "$val"
    ENV_KEYS+=("$key")
  done <"$file"
  for key in OLLAMA_HOST OLLAMA_MODELS MODELS_MIN_FREE_GB; do
    [ -n "${!key:-}" ] || die "cluster.env: $key is not set" 1
  done
}

api_url() { echo "http://$OLLAMA_HOST"; }

# pids of "ollama serve" processes of this user (a runner is also called ollama, its cmdline differs)
is_serve() { # pid
  local words
  words="$(tr '\0' ' ' <"$PROC/$1/cmdline" 2>/dev/null)" || return 1
  [[ $words =~ ^([^ ]*/)?ollama\ serve([[:space:]]|$) ]]
}

pgrep_pids() {
  pgrep -u "$(id -un)" -x ollama 2>/dev/null || true
}

serve_pids() {
  local pid
  for pid in $(pgrep_pids); do
    ! is_serve "$pid" || echo "$pid"
  done
}

# pids that listen on the Ollama port (ss -p shows only our own processes)
listener_pids() {
  local port="${OLLAMA_HOST##*:}"
  { ss -H -ltnp 2>/dev/null || true; } | grep -F ":$port " | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u
}
