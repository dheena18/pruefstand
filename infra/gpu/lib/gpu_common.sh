#!/usr/bin/env bash
# Shared helpers of the VM scripts switch-mode.sh, health.sh, fetch-model.sh, unload-all.sh (sourced, never run).
#
# The scripts NEVER take the lock themselves: the caller holds it (pruefstand-lock <cmd> or the orchestrator) and
# exports PRUEFSTAND_LOCK_HELD=1; without it a script exits 2 at once (D211, D212). They only talk to the one
# Ollama server through its native API (/api/generate, /api/ps, /api/tags; never /v1/*) and to the cluster
# through cluster_op. JSON bodies come from gpu_catalogue.py, never from string concatenation. DRY=1 prints
# every mutation as DRY-RUN instead of running it; reads still run.

GPU_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC2034  # LOCK_DIR is read by the scripts that source this file
LOCK_DIR="${PRUEFSTAND_LOCK_DIR:-/var/lib/pruefstand}"
DRY=0
# shellcheck source=cluster_ssh.sh
. "$GPU_DIR/lib/cluster_ssh.sh"

say() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
die() { # message [exit code]
  printf '%s: %s\n' "$(basename "$0")" "$1" >&2
  exit "${2:-1}"
}

require_lock() {
  [ "${PRUEFSTAND_LOCK_HELD:-}" = 1 ] ||
    die "run under the GPU lock: PRUEFSTAND_LOCK_HELD=1 not set (pruefstand-lock <cmd>, e.g. make gpu-up)" 2
}

PY="${PRUEFSTAND_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x "$GPU_DIR/../../.venv/bin/python" ]; then PY="$GPU_DIR/../../.venv/bin/python"; else PY="python3"; fi
fi
cat_py() { "$PY" "$GPU_DIR/gpu_catalogue.py" "$@"; }

lane_url() { # gpu0|gpu1 -> base URL of the lane (both name the same server, ADR-0018)
  local url
  case "$1" in
    gpu0) url="${OLLAMA_GPU0_URL:-http://127.0.0.1:11434}" ;;
    gpu1) url="${OLLAMA_GPU1_URL:-http://127.0.0.1:11434}" ;;
    *) die "unknown lane $1" 64 ;;
  esac
  [[ $url =~ ^https?://[A-Za-z0-9._:-]+$ ]] || die "invalid Ollama URL setting" 64
  echo "$url"
}

distinct_urls() { { lane_url gpu0; lane_url gpu1; } | sort -u; }

api_get() { # base-url path
  curl -sf --max-time 15 "$1/api/$2"
}

post_json() { # base-url api-path body
  if [ "$DRY" -eq 1 ]; then
    say "DRY-RUN POST $1/api/$2 $3"
    return 0
  fi
  curl -sS -f --max-time "${LOAD_TIMEOUT_S:-900}" -X POST -H 'Content-Type: application/json' -d "$3" "$1/api/$2" >/dev/null
}

cluster_mut() { # op [tag]: a cluster call that changes something
  if [ "$DRY" -eq 1 ]; then
    say "DRY-RUN cluster $*"
    return 0
  fi
  cluster_op "$@"
}

ensure_server() { # wait-seconds: start the server once (only if none answers), then wait for /api/tags
  local wait="$1" url started=0 deadline
  while IFS= read -r url; do
    ! api_get "$url" tags >/dev/null 2>&1 || continue
    if [ "$started" -eq 0 ]; then
      say "no Ollama server answers on $url; starting one through the cluster script (it reuses a running one)"
      cluster_mut start-ollama
      started=1
    fi
    [ "$DRY" -eq 0 ] || continue
    deadline=$((SECONDS + wait))
    until api_get "$url" tags >/dev/null 2>&1; do
      [ "$SECONDS" -lt "$deadline" ] || die "no Ollama server answers on $url after ${wait}s" 1
      sleep "${REPAIR_POLL_S:-5}"
    done
  done < <(distinct_urls)
}

residents() { # TSV: url name digest context size size_vram of every resident model
  local url body row
  while IFS= read -r url; do
    body="$(api_get "$url" ps 2>/dev/null)" || continue
    while IFS= read -r row; do
      printf '%s\t%s\n' "$url" "$row"
    done < <(printf '%s' "$body" | cat_py ps-rows)
  done < <(distinct_urls)
}

load_model() { # tag url: preload with exactly the catalogue options (the embed fallback for embedding-only models)
  # An embedding-only model answers /api/generate with HTTP 400 (expected, T3.1d D953): that attempt is quiet, the
  # /api/embed fallback is not. For every other role a failure of /api/generate stays visible.
  if [ "$(cat_py role "$1")" != embed ]; then
    post_json "$2" generate "$(cat_py preload-body "$1")" && return 0
    return 1
  fi
  post_json "$2" generate "$(cat_py preload-body "$1")" 2>/dev/null && return 0
  post_json "$2" embed "$(cat_py preload-body "$1" --embed)"
}

unload_model() { # tag url
  say "unloading $1"
  post_json "$2" generate "$(cat_py unload-body "$1")" && return 0
  [ "$(cat_py role "$1")" = embed ] || return 1
  post_json "$2" embed "$(cat_py unload-body "$1" --embed)"
}

# Make the server hold exactly the mode's catalogue models (round 12 A12-M12): unload catalogue models outside the
# mode first (a killed job's e5 or RQ2 candidate), leave other users' models alone (WARN), then load what is missing.
normalise_mode() { # mode
  local mode="$1" row tag server ctx url name rctx
  local -A res_url=() res_ctx=() wanted=() known=()
  local -a want=()
  mapfile -t want < <(cat_py mode-set "$mode")
  [ "${#want[@]}" -gt 0 ] || die "empty model set for mode $mode" 1
  while IFS= read -r name; do known["$name"]=1; done < <(cat_py catalogue-tags)
  for row in "${want[@]}"; do
    IFS=$'\t' read -r _ tag _ _ _ _ <<<"$row"
    wanted["$tag"]=1
  done
  while IFS=$'\t' read -r url name _ rctx _ _; do
    [ -n "$name" ] || continue
    res_url["$name"]="$url"
    res_ctx["$name"]="$rctx"
  done < <(residents)
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    [ -z "${wanted[$name]:-}" ] || continue
    if [ -n "${known[$name]:-}" ]; then
      unload_model "$name" "${res_url[$name]}"
    else
      warn "$name is resident but not a catalogue model; left alone"
    fi
  done < <(printf '%s\n' "${!res_url[@]}" | sort)
  for row in "${want[@]}"; do
    IFS=$'\t' read -r _ tag server _ ctx _ <<<"$row"
    url="$(lane_url "$server")"
    if [ -n "${res_url[$tag]:-}" ]; then
      if [ "${res_ctx[$tag]}" = "-" ] || [ "${res_ctx[$tag]}" = "$ctx" ]; then
        say "$tag already resident"
        continue
      fi
      say "$tag is resident with context ${res_ctx[$tag]}, not $ctx: reloading"
      unload_model "$tag" "${res_url[$tag]}"
    fi
    say "loading $tag"
    load_model "$tag" "$url"
  done
}
