#!/usr/bin/env bash
# Job hygiene for the persistent private runner (T6.2a S9; D100, D211). Called by job_started.sh and
# job_completed.sh (ACTIONS_RUNNER_HOOK_JOB_STARTED/_COMPLETED in the runner .env). Idempotent. Removes ONLY:
# the job workspace contents under the runner's _work/, Docker containers/networks/volumes labelled
# pruefstand.job, Qdrant collections named pr_*, and cache overlays named pr-* under $PRUEFSTAND_HOME/cache/.
# Never the shared cache, baselines, model weights or the owner's dev stack (compose profile dev, Y1.4).
set -euo pipefail

QDRANT="${PRUEFSTAND_QDRANT_URL:-http://127.0.0.1:6333}"

wipe_workspace() {
  local ws="${GITHUB_WORKSPACE:-}"
  case "$ws" in
    */_work/*) [ -d "$ws" ] && find "$ws" -mindepth 1 -delete ;;
    *) echo "job_cleanup: no runner workspace to wipe" >&2 ;;
  esac
}

remove_labelled() {
  docker ps -aq --filter label=pruefstand.job | xargs -r docker rm -f >/dev/null
  docker network ls -q --filter label=pruefstand.job | xargs -r docker network rm >/dev/null
  docker volume ls -q --filter label=pruefstand.job | xargs -r docker volume rm >/dev/null
}

drop_pr_collections() {
  local names name
  if ! names="$(curl -fsS -m 10 "$QDRANT/collections" | jq -r '.result.collections[].name')"; then
    echo "job_cleanup: qdrant not reachable, no collection dropped" >&2
    return 0
  fi
  for name in $names; do
    case "$name" in
      pr_*) curl -fsS -m 30 -X DELETE "$QDRANT/collections/$name" >/dev/null ;;
    esac
  done
}

drop_overlays() {
  if [ -z "${PRUEFSTAND_HOME:-}" ]; then
    echo "job_cleanup: PRUEFSTAND_HOME unset, no overlay dropped" >&2
    return 0
  fi
  local cache="$PRUEFSTAND_HOME/cache"
  [ -d "$cache" ] || return 0
  find "$cache" -mindepth 1 -maxdepth 1 -type d -name 'pr-*' -exec rm -rf -- {} +
}

wipe_workspace
remove_labelled
drop_pr_collections
drop_overlays
