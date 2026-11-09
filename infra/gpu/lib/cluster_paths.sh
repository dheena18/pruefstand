#!/usr/bin/env bash
# cluster_data_root: print the owner-supplied data root on the cluster (T3.1c, D950). Sourced, never run.
#
# The real path (models, scripts and log live below it) is NOT in this public repository. The owner supplies it once
# on the VM, either as the environment variable PRUEFSTAND_CLUSTER_DATA_ROOT or, for everything that runs without
# the owner's environment (sudo, the executor, health.sh), as the first line of the world-readable file
# /etc/pruefstand/cluster-data-root (PRUEFSTAND_CLUSTER_DATA_ROOT_FILE overrides the file name; test seam).
# The value is an absolute path of plain characters: no "..", no trailing "/", nothing a shell could expand.
# Derived locations: <root>/Models, <root>/pruefstand-bin (+ "-dev"), <root>/ollama.log.
# Exit: 0 printed; 78 not configured or invalid (message on stderr, no value echoed).

_CLUSTER_ROOT_RE='^/[A-Za-z0-9_][A-Za-z0-9_./-]*$'

cluster_data_root() {
  local file="${PRUEFSTAND_CLUSTER_DATA_ROOT_FILE:-/etc/pruefstand/cluster-data-root}" v="${PRUEFSTAND_CLUSTER_DATA_ROOT:-}"
  if [ -z "$v" ]; then
    if [ -r "$file" ]; then IFS= read -r v <"$file" || true; fi
  fi
  if [ -z "$v" ]; then
    echo "cluster data root not configured: set PRUEFSTAND_CLUSTER_DATA_ROOT or write it as one line to $file (docs/ops/runbook.md)" >&2
    return 78
  fi
  if ! [[ $v =~ $_CLUSTER_ROOT_RE ]] || [[ $v == *..* ]] || [[ $v == */ ]]; then
    echo "cluster data root is invalid (absolute path of [A-Za-z0-9_./-], no .., no trailing /)" >&2
    return 78
  fi
  printf '%s\n' "$v"
}
