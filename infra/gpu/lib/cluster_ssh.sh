#!/usr/bin/env bash
# cluster_op <op> [tag [bytes]]: the ONE way the VM scripts reach the cluster (T3.1a, Y1.1, D211). Sourced, never run.
#
# ops (nothing else, fail closed with 64): start-ollama | stop-ollama | status | rm <tag> | show <tag> | log [N] |
#   pull <tag> <bytes>   (<bytes> = the catalogue size; the cluster re-checks it against the free space, exit 17)
#   tag matches ^[a-z0-9._:/-]+$, does not start with "-" and contains no "..".
# As the service user (PRUEFSTAND_SERVICE_USER, default pruefstand: the only holder of the cluster key) the op
# runs over ssh against the scripts in /data/dheena/pruefstand-bin; as anyone else it goes through
#   sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster <op> [tag] [--bin-dev]
# which re-validates against its installed allow-list (it takes the size from there, not from the caller) and, for the
# mutating ops, demands proof that the GPU lock is held by an ancestor process (A12-M5, M1).
# PRUEFSTAND_BIN_DEV=1 selects /data/dheena/pruefstand-bin-dev (A11-M11). CLUSTER_SSH_HOST: the ssh alias.

CLUSTER_BIN_BASE="/data/dheena/pruefstand-bin"
_CLUSTER_TAG_RE='^[a-z0-9._:/-]+$'
_CLUSTER_LOG_N_RE='^[1-9][0-9]{0,3}$'
_CLUSTER_BYTES_RE='^[1-9][0-9]{0,14}$'

_cluster_tag_ok() { # tag
  [[ $1 =~ $_CLUSTER_TAG_RE ]] || return 1
  [[ $1 != -* ]] || return 1
  [[ $1 != *..* ]] || return 1
}

cluster_op() { # op [tag [bytes]]
  local op="${1:-}" tag="${2:-}" bytes="${3:-}" dir="$CLUSTER_BIN_BASE" remote host
  local -a args=("$op")
  case "$op" in
    start-ollama | stop-ollama | status)
      if [ "$#" -ne 1 ]; then return 64; fi
      ;;
    log)
      if [ "$#" -gt 2 ]; then return 64; fi
      if [ "$#" -eq 2 ]; then
        [[ $tag =~ $_CLUSTER_LOG_N_RE ]] || return 64
        [ "$tag" -le 1000 ] || return 64
        args+=("$tag")
      fi
      ;;
    rm | show)
      if [ "$#" -ne 2 ]; then return 64; fi
      _cluster_tag_ok "$tag" || return 64
      args+=("$tag")
      ;;
    pull)
      if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then return 64; fi
      _cluster_tag_ok "$tag" || return 64
      args+=("$tag")
      ;;
    *) return 64 ;;
  esac
  if [ "${PRUEFSTAND_BIN_DEV:-}" = 1 ]; then dir="$CLUSTER_BIN_BASE-dev"; fi
  if [ "$(id -un)" = "${PRUEFSTAND_SERVICE_USER:-pruefstand}" ]; then
    host="${CLUSTER_SSH_HOST:-cairo-s101lp}"
    case "$op" in
      pull)
        [[ $bytes =~ $_CLUSTER_BYTES_RE ]] || return 64
        remote="bash $dir/ollama-op.sh pull $tag $bytes"
        ;;
      log) remote="bash $dir/log-tail.sh ${tag:-200}" ;;
      rm | show) remote="bash $dir/ollama-op.sh $op $tag" ;;
      *) remote="bash $dir/$op.sh" ;;
    esac
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" "$remote"
    return
  fi
  if [ "${PRUEFSTAND_BIN_DEV:-}" = 1 ]; then args+=(--bin-dev); fi
  sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster "${args[@]}"
}
