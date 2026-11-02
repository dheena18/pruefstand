#!/usr/bin/env bash
# Read-only status of the ONE Ollama server and the GPUs, as CSV `check,status,detail` (ADR-0018, ADR-0019).
#
# usage: status.sh            (no arguments; writes nothing on the cluster)
# status: OK | INFO | WARN | FAIL; exit 1 when any row is FAIL (the CSV is complete anyway), else 0.
# Rows: server, second-server (FAIL when two `ollama serve` run), listener, start-script (WARN when the start script of
# record `~/start-ollama.sh` is missing, a dangling link or not executable), env / env:<KEY> (WARN per key that
# differs from cluster.env), disk-models (WARN below MODELS_MIN_FREE_GB), api-tags, ps:<tag> (size, size_vram,
# digest), gpu:<index>, gpu-proc:<pid> (WARN for a pid that is not ours), placement:<tag> (the card(s) of every
# resident model: the model's blob in its manifest, matched to the runner process whose command line names that
# blob, matched to nvidia-smi --query-compute-apps by pid and to the card by gpu_uuid), bin-integrity
# (sha256sum -c SHA256SUMS in this directory), bin-sums (sha256 of SHA256SUMS: health.sh exit 14).
# The values of OLLAMA_MODELS, $HOME and the login are scrubbed from every detail (<models-dir>, <home>, <cluster-user>).
set -euo pipefail

BIN="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
. "$BIN/common.sh"
[ "$#" -eq 0 ] || die "usage: status.sh   (no arguments)" 2
load_cluster_env "$BIN/cluster.env"

FAILED=0
LOGIN="$(id -un)"
emit() { # check status detail
  local d="${3//,/;}"
  d="${d//"$OLLAMA_MODELS"/<models-dir>}"
  d="${d//"$HOME"/<home>}"
  [ "${#LOGIN}" -lt 4 ] || d="${d//"$LOGIN"/<cluster-user>}"
  printf '%s,%s,%s\n' "$1" "$2" "$d"
  [ "$2" != FAIL ] || FAILED=1
}

declare -A UUID_IDX=() PID_GPU=()
API="$(api_url)"
echo "check,status,detail"

check_server() {
  mapfile -t serve < <(serve_pids)
  case "${#serve[@]}" in
    0) emit server FAIL "no ollama serve process of $LOGIN" ;;
    1) emit server OK "pid=${serve[0]}" ;;
    *)
      emit server FAIL "${#serve[@]} ollama serve processes"
      emit second-server FAIL "pids=${serve[*]}"
      ;;
  esac
  mapfile -t listeners < <(listener_pids)
  if [ "${#listeners[@]}" -eq 0 ]; then
    emit listener FAIL "nothing listens on $OLLAMA_HOST"
  elif [ "${#serve[@]}" -ge 1 ] && printf '%s\n' "${serve[@]}" | grep -qx "${listeners[0]}"; then
    emit listener OK "$OLLAMA_HOST pid=${listeners[0]}"
  else
    emit listener WARN "$OLLAMA_HOST is served by pid ${listeners[0]}, which is not the ollama serve found"
  fi
}

check_env() {
  local pid key want got diff=0 dump
  pid="${serve[0]:-}"
  [ -n "$pid" ] || return 0
  if ! dump="$(tr '\0' '\n' <"$PROC/$pid/environ" 2>/dev/null)"; then
    emit env WARN "environ of pid $pid is not readable"
    return 0
  fi
  for key in "${ENV_KEYS[@]}"; do
    case "$NON_SERVER_KEYS" in *" $key "*) continue ;; esac
    want="${!key}"
    got="unset"
    if grep -q "^$key=" <<<"$dump"; then
      got="$(sed -n "s/^$key=//p" <<<"$dump" | head -n 1)"
    fi
    if [ "$got" != "$want" ]; then
      emit "env:$key" WARN "expected=$want actual=$got (owner step: runbook 2a)"
      diff=1
    fi
  done
  [ "$diff" -eq 1 ] || emit env OK "matches cluster.env"
}

check_disk() {
  local free_kb min_kb=$((MODELS_MIN_FREE_GB * 1024 * 1024)) st=OK
  free_kb="$(df -Pk "$OLLAMA_MODELS" 2>/dev/null | awk 'END{print $4}')" || free_kb=0
  if ! [[ $free_kb =~ ^[0-9]+$ ]]; then free_kb=0; fi
  if [ "$free_kb" -lt "$min_kb" ]; then st=WARN; fi
  emit disk-models "$st" "free_kb=$free_kb min_free_gb=$MODELS_MIN_FREE_GB"
}

check_start_script() {
  if [ -f "$OLLAMA_START_SCRIPT" ] && [ -x "$OLLAMA_START_SCRIPT" ]; then
    emit start-script OK "the start script of record exists"
  else
    emit start-script WARN 'the start script ~/start-ollama.sh is missing or not executable: create it (a link is fine) so that it sets every value of cluster.env'
  fi
}

check_gpus() {
  local out line idx uuid used total
  if ! out="$(nvidia-smi --query-gpu=index,uuid,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null)"; then
    emit gpu WARN "nvidia-smi unavailable"
    return 0
  fi
  while IFS=',' read -r idx uuid used total; do
    [ -n "${idx// /}" ] || continue
    idx="${idx// /}"
    uuid="${uuid// /}"
    UUID_IDX["$uuid"]="$idx"
    emit "gpu:$idx" INFO "uuid=$uuid used_mib=${used// /} total_mib=${total// /}"
  done <<<"$out"
  out="$(nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits 2>/dev/null || true)"
  while IFS=',' read -r pid uuid used; do
    pid="${pid// /}"
    if ! [[ $pid =~ ^[0-9]+$ ]]; then continue; fi
    uuid="${uuid// /}"
    idx="${UUID_IDX[$uuid]:-?}"
    PID_GPU["$pid"]="$idx"
    if grep -aq ollama "$PROC/$pid/cmdline" 2>/dev/null; then
      emit "gpu-proc:$pid" INFO "gpu=$idx used_mib=${used// /}"
    else
      emit "gpu-proc:$pid" WARN "foreign process gpu=$idx used_mib=${used// /} (not an ollama process)"
    fi
  done <<<"$out"
}

manifest_blob() { # tag -> hex digest of the model layer (empty if unknown)
  local name="${1%%:*}" ver="latest" path
  [[ $1 == *:* ]] && ver="${1#*:}"
  [[ $name == */* ]] || name="library/$name"
  path="$OLLAMA_MODELS/manifests/registry.ollama.ai/$name/$ver"
  [ -r "$path" ] || return 0
  tr -d '\n' <"$path" | sed -E 's/\{/\n{/g' | grep -F 'vnd.ollama.image.model' |
    sed -nE 's/.*"digest": *"sha256:([0-9a-f]{64})".*/\1/p' | head -n 1
}

ps_gpus() { # hex of the model blob -> "0" | "0+1" | "" (the cards of the runner processes using that blob)
  local f pid
  while IFS= read -r f; do
    pid="${f%/cmdline}"
    pid="${pid##*/}"
    [ -z "${PID_GPU[$pid]:-}" ] || echo "${PID_GPU[$pid]}"
  done < <(grep -laF -- "sha256-$1" "$PROC"/[0-9]*/cmdline 2>/dev/null || true) | sort -u | tr '\n' '+' | sed 's/+$//'
}

check_ps() {
  local body line name size vram digest hex gpus
  body="$(curl -sf --max-time 10 "$API/api/ps" 2>/dev/null || true)"
  [ -n "$body" ] || {
    emit ps WARN "/api/ps did not answer"
    return 0
  }
  while IFS= read -r line; do
    name="$(sed -nE 's/^\{"name": *"([^"]*)".*/\1/p' <<<"$line")"
    [ -n "$name" ] || continue
    size="$(sed -nE 's/.*"size": *([0-9]+).*/\1/p' <<<"$line")"
    vram="$(sed -nE 's/.*"size_vram": *([0-9]+).*/\1/p' <<<"$line")"
    digest="$(sed -nE 's/.*"digest": *"([0-9a-f]+)".*/\1/p' <<<"$line")"
    emit "ps:$name" INFO "size=$size size_vram=$vram digest=$digest"
    hex="$(manifest_blob "$name")"
    gpus=""
    [ -z "$hex" ] || gpus="$(ps_gpus "$hex")"
    case "$gpus" in
      '') emit "placement:$name" WARN "gpu=unknown (no runner process matched the model blob)" ;;
      *+*) emit "placement:$name" WARN "gpu=$gpus spread over both cards" ;;
      *) emit "placement:$name" OK "gpu=$gpus" ;;
    esac
  done < <(sed -E 's/\{ *"name" *:/\n{"name":/g' <<<"$body")
}

check_bin() {
  if [ ! -r "$BIN/SHA256SUMS" ]; then
    emit bin-integrity WARN "no SHA256SUMS in the bin dir (run deploy-cluster-bin.sh)"
    return 0
  fi
  if (cd "$BIN" && sha256sum -c --quiet SHA256SUMS >/dev/null 2>&1); then
    emit bin-integrity OK "sha256sum -c passed"
  else
    emit bin-integrity FAIL "sha256sum -c SHA256SUMS failed: the scripts differ from the deployed set"
  fi
  emit bin-sums INFO "sha256=$(sha256sum "$BIN/SHA256SUMS" | cut -d' ' -f1)"
}

ENV_TMP="$(mktemp)"
trap 'rm -f "$ENV_TMP"' EXIT
check_server
check_env
check_disk
check_start_script
if tags="$(curl -sf --max-time 10 "$API/api/tags" 2>/dev/null)"; then
  emit api-tags OK "models=$(grep -o '"name":' <<<"$tags" | wc -l | tr -d ' ')"
else
  emit api-tags FAIL "/api/tags does not answer on $OLLAMA_HOST"
fi
check_gpus
check_ps
check_bin
exit "$FAILED"
