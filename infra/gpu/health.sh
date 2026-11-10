#!/usr/bin/env bash
# health.sh [--repair] [--mode day|night]: CSV `check,status,detail` + exit code (VM; interfaces 1.5, ADR-0018/0019).
#
# Runs UNDER the GPU lock (exit 2 without PRUEFSTAND_LOCK_HELD=1), never takes it. Checks: the data root (ADR-0019),
# every endpoint (/api/tags), `status.sh` over ssh (free VRAM, the card of every model, env, disk, bin dir), and
# /api/ps against the catalogue (residency, digests, size_vram == size, one card). Exit codes, the first of this
# order that applies: 16 data root unavailable ($PRUEFSTAND_DATA_ROOT missing, not writable, or less than
# PRUEFSTAND_DATA_ROOT_MIN_FREE_GB = 20 GB free), 11 an endpoint or a mode model is not answering/resident (also a
# second `ollama serve`), 12 status.sh unreachable (ssh), 14 the cluster bin dir is not the checkout's
# (`deploy-cluster-bin.sh`), 13 a resident digest differs from the catalogue, 15 a model not fully in VRAM or spread over
# both cards, 10 free VRAM below PRUEFSTAND_MIN_FREE_VRAM_MIB (1024) on a card; 0 ok (WARN rows do not fail: free
# disk < 2 GB, env differences, models of other users).
# --repair first starts the server through the cluster script ONLY if no endpoint answers (waits <= REPAIR_WAIT_S,
# default 300), then normalises the server to exactly the mode's model set (unload catalogue models outside it, load
# the missing ones), then checks. --mode defaults to day; night loads the same set (ADR-0019).
set -euo pipefail

# shellcheck source=lib/gpu_common.sh
. "$(cd "$(dirname "$0")" && pwd)/lib/gpu_common.sh"
require_lock

repair=0
mode=day
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repair) repair=1 ;;
    --mode)
      [ "$#" -ge 2 ] || die "usage: health.sh [--repair] [--mode day|night]" 64
      mode="$2"
      shift
      ;;
    *) die "usage: health.sh [--repair] [--mode day|night]" 64 ;;
  esac
  shift
done
case "$mode" in day | night) ;; *) die "unknown mode $mode: use day or night" 64 ;; esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
rows=()
codes=()
row() { rows+=("$1,$2,${3//,/;}"); }

check_data_root() {
  local root="${PRUEFSTAND_DATA_ROOT:-/mnt/pruefstand}" min="${PRUEFSTAND_DATA_ROOT_MIN_FREE_GB:-20}" free_kb
  if [ ! -d "$root" ]; then
    row data-root FAIL "the data root does not exist"
  elif [ ! -w "$root" ]; then
    row data-root FAIL "the data root is not writable by $(id -un)"
  else
    free_kb="$(df -Pk "$root" | awk 'END{print $4}')"
    if [ "${free_kb:-0}" -ge $((min * 1024 * 1024)) ]; then
      row data-root OK "free_gb=$((free_kb / 1024 / 1024)) min_free_gb=$min"
      return 0
    fi
    row data-root FAIL "free_gb=$((${free_kb:-0} / 1024 / 1024)) is below min_free_gb=$min"
  fi
  codes+=(16)
}

check_endpoints() {
  local url n=0
  while IFS= read -r url; do
    if api_get "$url" tags >/dev/null 2>&1; then
      row "endpoint:$url" OK "/api/tags answers"
      api_get "$url" ps >"$tmp/ps-$n.json" 2>/dev/null || echo '{"models":[]}' >"$tmp/ps-$n.json"
    else
      row "endpoint:$url" FAIL "/api/tags does not answer"
      echo '{"models":[]}' >"$tmp/ps-$n.json"
      codes+=(11)
    fi
    n=$((n + 1))
  done < <(distinct_urls)
}

check_cluster() { # returns 1 when status.sh gave nothing usable
  local rc=0
  cluster_op status >"$tmp/status.csv" 2>"$tmp/status.err" || rc=$?
  if [ "$rc" -eq 78 ]; then
    row cluster-status FAIL "cluster data root not configured or untrusted (docs/ops/runbook.md); status.sh was not run"
    codes+=(12)
    return 1
  fi
  if [ "$rc" -eq 255 ] || ! head -n 1 "$tmp/status.csv" | grep -q '^check,status,detail$'; then
    row cluster-status FAIL "status.sh did not answer over ssh (rc=$rc)"
    codes+=(12)
    return 1
  fi
  row cluster-status OK "status.sh answered"
}

check_data_root
if [ "$repair" -eq 1 ]; then
  { # the progress text goes to stderr: stdout is the CSV only
    ensure_server "${REPAIR_WAIT_S:-300}"
    normalise_mode "$mode"
  } >&2
fi
check_endpoints
if check_cluster; then
  sums_rc=0
  sums="$(bash "$GPU_DIR/deploy-cluster-bin.sh" --print-sums 2>"$tmp/sums.err")" || sums_rc=$?
  expected=""
  if [ "$sums_rc" -eq 0 ]; then
    expected="$(printf '%s\n' "$sums" | sha256sum | cut -d' ' -f1)"
  elif [ "$sums_rc" -eq 78 ]; then
    echo "health.sh: cluster data root not configured: $(head -n 1 "$tmp/sums.err")" >&2
    row bin-dir-config FAIL "cluster data root not configured or untrusted (docs/ops/runbook.md); the bin-dir check cannot pass"
  fi
  analysis="$("$PY" "$GPU_DIR/gpu_health.py" --mode "$mode" --ps "$tmp"/ps-*.json --status "$tmp/status.csv" \
    --expected-sums "$expected" --min-free-vram-mib "${PRUEFSTAND_MIN_FREE_VRAM_MIB:-1024}")"
  while IFS= read -r line; do
    case "$line" in
      CODES:*) IFS=',' read -r -a more <<<"${line#CODES:}"; codes+=("${more[@]}") ;;
      '') ;;
      *) rows+=("$line") ;;
    esac
  done <<<"$analysis"
fi

echo "check,status,detail"
printf '%s\n' "${rows[@]}"
for code in 16 11 12 14 13 15 10; do
  for have in "${codes[@]:-}"; do
    [ "$have" != "$code" ] || exit "$code"
  done
done
exit 0
