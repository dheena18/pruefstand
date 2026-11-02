#!/usr/bin/env bash
# pull | rm | show against the ONE server (store: OLLAMA_MODELS), called by pruefstand-cluster / the VM scripts.
#
# usage: ollama-op.sh pull <tag> <bytes> | rm <tag> | show <tag>
#   tag matches ^[a-z0-9._:/-]+$, does not start with "-" and has no "..".
#   pull  <bytes> is the model's size from the catalogue; the script refuses (exit 17) when the models filesystem
#         would keep less than bytes + MODELS_MIN_FREE_GB free (ADR-0019, the owner's disk rule: the shared disk
#         has little room, so the owner must free space first). An unreadable free-space value is exit 17 too.
#   rm    never removes the generator ($GENERATOR_TAG): exit 64
# The binary is taken from the process that serves the port (a non-interactive ssh has a minimal PATH).
# Exit: 0 ok, 1 no binary / the command failed, 17 not enough free space, 64 usage or forbidden.
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"

usage="usage: ollama-op.sh pull <tag> <bytes> | rm <tag> | show <tag>"
if [ "$#" -lt 2 ]; then die "$usage" 64; fi
op="$1"
tag="$2"
bytes=""
case "$op" in
  pull)
    if [ "$#" -ne 3 ]; then die "$usage" 64; fi
    bytes="$3"
    bytes_re='^[0-9]{1,15}$'
    if ! [[ $bytes =~ $bytes_re ]]; then die "pull needs the model size in bytes" 64; fi
    ;;
  rm | show)
    if [ "$#" -ne 2 ]; then die "$usage" 64; fi
    ;;
  *) die "unknown operation '$op'" 64 ;;
esac
tag_re='^[a-z0-9._:/-]+$'
if ! [[ $tag =~ $tag_re ]] || [[ $tag == -* ]] || [[ $tag == *..* ]]; then die "invalid model tag" 64; fi
load_cluster_env "$BIN/cluster.env"

if [ "$op" = rm ] && [ "$tag" = "$GENERATOR_TAG" ]; then die "refusing to remove the generator $GENERATOR_TAG" 64; fi

if [ "$op" = pull ]; then
  free_kb="$(df -Pk "$OLLAMA_MODELS" 2>/dev/null | awk 'END{print $4}')" || free_kb=""
  kb_re='^[0-9]+$'
  if ! [[ $free_kb =~ $kb_re ]]; then
    die "cannot read the free space of the models filesystem: not pulling; ask the owner" 17
  fi
  need_kb=$(((bytes + 1023) / 1024 + MODELS_MIN_FREE_GB * 1024 * 1024))
  if [ "$free_kb" -lt "$need_kb" ]; then
    die "$free_kb KiB free, $need_kb KiB needed (model plus the ${MODELS_MIN_FREE_GB} GB reserve): not pulling; ask the owner to free space first" 17
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
