#!/usr/bin/env bash
# Job hygiene for the persistent private runner (T6.2a S9; D100, D211). Called by job_started.sh and
# job_completed.sh (ACTIONS_RUNNER_HOOK_JOB_STARTED/_COMPLETED in the runner .env). Idempotent. Removes ONLY:
# the job workspace contents under the runner's _work/, Docker containers/networks/volumes labelled
# pruefstand.job, Qdrant collections named pr_*, and cache overlays named pr-* under $PRUEFSTAND_HOME/cache/.
# Never the shared cache, baselines, model weights or the owner's dev stack (compose profile dev, Y1.4).
set -euo pipefail
set -f  # no pathname expansion anywhere in this script (review #202)

QDRANT="${PRUEFSTAND_QDRANT_URL:-http://127.0.0.1:6333}"

# Wipes only a canonical directory below a runner `_work/` dir: no `.`/`..` components and no symlink on
# the way (realpath must equal the given path), so a crafted GITHUB_WORKSPACE cannot reach anything else.
wipe_workspace() {
  local ws="${GITHUB_WORKSPACE:-}" real
  if [ -z "$ws" ]; then
    echo "job_cleanup: no runner workspace to wipe" >&2
    return 0
  fi
  ws="${ws%/}"
  case "/$ws/" in
    */../* | */./*)
      echo "job_cleanup: workspace has . or .. components, not wiped" >&2
      return 0
      ;;
  esac
  case "$ws" in
    /*/_work/?*) ;;
    *)
      echo "job_cleanup: workspace is not below a runner _work dir, not wiped" >&2
      return 0
      ;;
  esac
  [ -d "$ws" ] || return 0
  real="$(realpath -e -- "$ws")"
  if [ "$real" != "$ws" ]; then
    echo "job_cleanup: workspace resolves through a symlink, not wiped" >&2
    return 0
  fi
  find "$real" -mindepth 1 -delete
}

remove_labelled() {
  docker ps -aq --filter label=pruefstand.job | xargs -r docker rm -f >/dev/null
  docker network ls -q --filter label=pruefstand.job | xargs -r docker network rm >/dev/null
  docker volume ls -q --filter label=pruefstand.job | xargs -r docker volume rm >/dev/null
}

drop_pr_collections() {
  local names name
  local auth=()
  [ -z "${QDRANT_API_KEY:-}" ] || auth=(-H "api-key: $QDRANT_API_KEY")  # D1089: the executor Qdrant needs it
  if ! names="$(curl -fsS -m 10 "${auth[@]}" "$QDRANT/collections" | jq -r '.result.collections[].name')"; then
    echo "job_cleanup: qdrant not reachable, no collection dropped" >&2
    return 0
  fi
  # one name per line, read literally: no word splitting, no globbing of names such as `pr_*`
  while IFS= read -r name; do
    case "$name" in
      pr_*) curl -fsS -m 30 "${auth[@]}" -X DELETE "$QDRANT/collections/$name" >/dev/null ;;
    esac
  done <<<"$names"
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
