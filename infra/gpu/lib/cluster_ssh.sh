#!/usr/bin/env bash
# cluster_op <op> [tag]: the ONE way the VM scripts reach the cluster (T3.1a, Y1.1, D211). Sourced, never run.
#
# ops (nothing else, fail closed with 64): start-ollama | stop-ollama | status | pull <tag> | rm <tag> | show <tag>
#   tag matches ^[a-z0-9._:/-]+$ and does not start with "-".
# As the service user (PRUEFSTAND_SERVICE_USER, default pruefstand: the only holder of the cluster key) the op
# runs over ssh against the scripts in /data/dheena/pruefstand-bin; as anyone else it goes through
#   sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster <op> [tag] [--bin-dev]
# which re-validates and, for the mutating ops, demands proof that the GPU lock is held (A12-M5).
# PRUEFSTAND_BIN_DEV=1 selects /data/dheena/pruefstand-bin-dev (A11-M11). CLUSTER_SSH_HOST: the ssh alias.

CLUSTER_BIN_BASE="/data/dheena/pruefstand-bin"
_CLUSTER_TAG_RE='^[a-z0-9._:/-]+$'

cluster_op() { # op [tag]
  local op="${1:-}" tag="${2:-}" dir="$CLUSTER_BIN_BASE" remote host
  case "$op" in
    start-ollama | stop-ollama | status) [ "$#" -eq 1 ] || return 64 ;;
    pull | rm | show)
      [ "$#" -eq 2 ] && [[ $tag =~ $_CLUSTER_TAG_RE ]] && [[ $tag != -* ]] || return 64
      ;;
    *) return 64 ;;
  esac
  [ "${PRUEFSTAND_BIN_DEV:-}" != 1 ] || dir="$CLUSTER_BIN_BASE-dev"
  if [ "$(id -un)" = "${PRUEFSTAND_SERVICE_USER:-pruefstand}" ]; then
    host="${CLUSTER_SSH_HOST:-cairo-s101lp}"
    case "$op" in
      pull | rm | show) remote="bash $dir/ollama-op.sh $op $tag" ;;
      *) remote="bash $dir/$op.sh" ;;
    esac
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" "$remote"
  elif [ "${PRUEFSTAND_BIN_DEV:-}" = 1 ]; then
    sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster "$@" --bin-dev
  else
    sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster "$@"
  fi
}
