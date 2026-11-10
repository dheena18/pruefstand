#!/usr/bin/env bash
# cluster_data_root: print the owner-supplied data root on the cluster (T3.1c, D950). Sourced, never run.
#
# The real path (models, scripts and log live below it) is NOT in this public repository. The owner supplies it once
# on the VM, either as the environment variable PRUEFSTAND_CLUSTER_DATA_ROOT (it wins) or, for everything that runs
# without the owner's environment (sudo, the executor, health.sh), as the first line of the file
# /etc/pruefstand/cluster-data-root (PRUEFSTAND_CLUSTER_DATA_ROOT_FILE overrides the file name; test seam).
# The FILE is trusted only when it cannot have been planted by an unprivileged user: a regular file (no symlink), owned
# by root, not writable by group or others, in a directory that is root-owned and not writable by group or others.
# PRUEFSTAND_CLUSTER_ROOT_FILE_UID (default 0) is a test seam for "root".
# The value is an absolute path of ASCII [A-Za-z0-9_./-] (checked in the C locale), at most 4096 characters, no "..",
# no trailing "/". Derived locations: <root>/Models, <root>/pruefstand-bin (+ "-dev"), <root>/ollama.log.
# Exit: 0 printed; 78 not configured, untrusted file or invalid value (message on stderr, the value is never echoed).

_cluster_file_trusted() { # file: the planted-file guard for the file source
  local file="$1" uid="${PRUEFSTAND_CLUSTER_ROOT_FILE_UID:-0}" dir mode owner
  if [ -L "$file" ] || ! [ -f "$file" ]; then
    echo "cluster data root file $file must be a regular file, not a symlink" >&2
    return 1
  fi
  dir="$(dirname -- "$file")"
  read -r owner mode < <(stat -c '%u %a' -- "$file") || return 1
  if [ "$owner" != "$uid" ] || [ $((8#$mode & 8#022)) -ne 0 ]; then
    echo "cluster data root file $file must be owned by root and not writable by group or others" >&2
    return 1
  fi
  read -r owner mode < <(stat -c '%u %a' -- "$dir") || return 1
  if [ "$owner" != "$uid" ] || [ $((8#$mode & 8#022)) -ne 0 ]; then
    echo "directory $dir must be owned by root and not writable by group or others" >&2
    return 1
  fi
}

cluster_data_root() {
  local LC_ALL=C
  local file="${PRUEFSTAND_CLUSTER_DATA_ROOT_FILE:-/etc/pruefstand/cluster-data-root}" v="${PRUEFSTAND_CLUSTER_DATA_ROOT:-}"
  local re='^/[A-Za-z0-9_][A-Za-z0-9_./-]*$'
  if [ -z "$v" ]; then
    if [ -e "$file" ] || [ -L "$file" ]; then
      _cluster_file_trusted "$file" || return 78
      IFS= read -r v <"$file" || true
    fi
  fi
  if [ -z "$v" ]; then
    echo "cluster data root not configured: set PRUEFSTAND_CLUSTER_DATA_ROOT or write it as one line to $file (docs/ops/runbook.md)" >&2
    return 78
  fi
  if [ "${#v}" -gt 4096 ] || ! [[ $v =~ $re ]] || [[ $v == *..* ]] || [[ $v == */ ]]; then
    echo "cluster data root is invalid (absolute ASCII path of [A-Za-z0-9_./-], at most 4096 characters, no .., no trailing /)" >&2
    return 78
  fi
  printf '%s\n' "$v"
}
