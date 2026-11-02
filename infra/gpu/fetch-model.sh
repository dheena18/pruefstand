#!/usr/bin/env bash
# fetch-model.sh <models.yaml id> [--dry-run]   |   fetch-model.sh --rm <id> [--dry-run]   (VM; ADR-0019, D207)
#
# Pull a catalogue model into the cluster's model store through the one server, then check its manifest digest
# against models.yaml (a mismatch removes the model again). UNDER the GPU lock; one pull at a time.
# DISK RULE (owner, binding): the shared cluster disk has little room. Right before every pull the free space of the
# models disk is read from the cluster (status.sh); if it is below model size + the 2 GB reserve, the script STOPS
# with exit 17 and asks the owner to free space (swap rule); it never starts the pull in that case.
# A model that is already present with the pinned digest is not pulled again. The size also goes to the cluster, which
# checks it against the free space again (ollama-op.sh, exit 17). Limit: a pull the owner starts by hand at the same time
# is invisible to this check; one pull at a time is a rule, not something the script can enforce.
# --rm <id> removes a non-generator catalogue model (swap rule) and only while the file MAINTENANCE exists.
# Exit: 0 ok, 1 pull failed / digest mismatch / space unreadable, 2 not under the lock, 3 --rm without MAINTENANCE,
# 17 not enough free disk space (ask the owner), 64 usage / unknown id / the generator with --rm.
set -euo pipefail

# shellcheck source=lib/gpu_common.sh
. "$(cd "$(dirname "$0")" && pwd)/lib/gpu_common.sh"
require_lock

usage="usage: fetch-model.sh <ollama/<tag>> [--dry-run] | --rm <ollama/<tag>> [--dry-run]"
remove=0
id=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --rm) remove=1 ;;
    -*) die "$usage" 64 ;;
    *) [ -z "$id" ] || die "$usage" 64; id="$arg" ;;
  esac
done
id_re='^ollama/[A-Za-z0-9._:/-]+$'
[[ $id =~ $id_re ]] || die "$usage" 64
row="$(cat_py lookup "$id")" || exit "$?"
IFS=$'\t' read -r tag digest role disk_bytes engine <<<"$row"
[ "$engine" = ollama ] || die "$id is not served by Ollama" 64
# the catalogue entry must carry the pin and the size the disk rule needs (gpu_catalogue.py checked them too)
if ! [[ $digest =~ ^[0-9a-f]{64}$ ]] || ! [[ $disk_bytes =~ ^[1-9][0-9]{0,14}$ ]]; then
  die "catalogue entry $id has no valid digest or disk_bytes; refusing" 1
fi

if [ "$remove" -eq 1 ]; then
  [ "$role" != generator ] || die "never remove the generator ($id)" 64
  [ -e "$LOCK_DIR/MAINTENANCE" ] || die "set MAINTENANCE for a model swap (see docs/engineering/gpu-cluster.md section 8)" 3
  cluster_mut rm "$tag"
  exit 0
fi

url="$(lane_url "$(cat_py server "$tag")")"
listed() { api_get "$url" tags 2>/dev/null | cat_py tag-digest "$tag" || true; }

present="$(listed)"
if [ "$present" = "$digest" ]; then
  say "$tag already present with the pinned digest; nothing to pull"
  exit 0
fi

# the disk rule: read the free space of the models disk right before the pull
status="$(cluster_op status 2>/dev/null)" || [ -n "$status" ] || die "cannot read the free space of the cluster disk (status.sh failed); not pulling" 1
free_kb="$(sed -n 's/^disk-models,[A-Z]*,.*free_kb=\([0-9]*\).*/\1/p' <<<"$status" | head -n 1)"
reserve_gb="$(sed -n 's/^disk-models,[A-Z]*,.*min_free_gb=\([0-9]*\).*/\1/p' <<<"$status" | head -n 1)"
if [ -z "$free_kb" ] || [ -z "$reserve_gb" ]; then
  die "status.sh reports no free space of the models disk; not pulling" 1
fi
need_kb=$(((disk_bytes + 1023) / 1024 + reserve_gb * 1024 * 1024))
if [ "$free_kb" -lt "$need_kb" ]; then
  die "free space first: swap rule. $tag needs $((need_kb / 1024)) MiB free (model plus the ${reserve_gb} GB reserve) but the cluster disk has $((free_kb / 1024)) MiB. Not pulling: ask the owner to free space" 17
fi

cluster_mut pull "$tag" "$disk_bytes"
actual="$(listed)"
if [ "$DRY" -eq 1 ] && [ -z "$actual" ]; then
  say "would verify the digest of $tag after the pull"
  exit 0
fi
if [ -z "$actual" ]; then
  # no digest at all (not listed, empty or unparsable /api/tags): never delete on a guess
  warn "could not read the digest of $tag from /api/tags after the pull; not removing it, check by hand"
  exit 1
fi
if [ "$actual" != "$digest" ]; then
  warn "$tag has digest $actual, the catalogue pins $digest: removing it"
  cluster_mut rm "$tag"
  exit 1
fi
say "$tag pulled; digest matches the catalogue"
