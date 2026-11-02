#!/usr/bin/env bash
# pull | rm | show <tag> against the ONE server (store: OLLAMA_MODELS), called by pruefstand-cluster / the VM scripts.
#
# usage: ollama-op.sh pull|rm|show <tag>        tag matches ^[a-z0-9._:/-]+$ and does not start with "-"
#   pull  refuses (exit 17) when the models disk would keep less than MODELS_MIN_FREE_GB free even before the
#         model arrives: the shared disk has little room (ADR-0019), so the owner must free space first;
#         the VM checks model size + reserve before it calls this (fetch-model.sh)
#   rm    never removes the generator ($GENERATOR_TAG): exit 64
# The binary is taken from the process that serves the port (a non-interactive ssh has a minimal PATH).
# Exit: 0 ok, 1 no binary / the command failed, 17 not enough free space, 64 usage or forbidden.
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"

[ "$#" -eq 2 ] || die "usage: ollama-op.sh pull|rm|show <tag>" 64
op="$1"
tag="$2"
case "$op" in pull | rm | show) ;; *) die "unknown operation '$op'" 64 ;; esac
tag_re='^[a-z0-9._:/-]+$'
[[ $tag =~ $tag_re ]] && [[ $tag != -* ]] || die "invalid model tag" 64
load_cluster_env "$BIN/cluster.env"

[ "$op" != rm ] || [ "$tag" != "$GENERATOR_TAG" ] || die "refusing to remove the generator $GENERATOR_TAG" 64

if [ "$op" = pull ]; then
  free_kb="$({ df -Pk "$OLLAMA_MODELS" 2>/dev/null || df -Pk /data; } | awk 'END{print $4}')"
  if [ "${free_kb:-0}" -lt $((MODELS_MIN_FREE_GB * 1024 * 1024)) ]; then
    die "only ${free_kb:-0} KiB free on the models disk (reserve ${MODELS_MIN_FREE_GB} GB): not pulling; ask the owner to free space first" 17
  fi
fi

bin=""
for pid in $(serve_pids); do
  exe="$(readlink "$PROC/$pid/exe" 2>/dev/null || true)"
  if [ -n "$exe" ] && [ -x "$exe" ] && [[ "$(basename "$exe")" == ollama* ]]; then
    bin="$exe"
    break
  fi
done
[ -n "$bin" ] || bin="$(command -v ollama || true)"
[ -n "$bin" ] || die "no ollama binary found (no server process and none on PATH)" 1

exec env OLLAMA_HOST="$OLLAMA_HOST" "$bin" "$op" "$tag"
