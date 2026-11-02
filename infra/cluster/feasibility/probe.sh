#!/usr/bin/env bash
# T0.6 S1: read-only probe of the cluster `cairo-s101lp`. It is PIPED over SSH, never copied:
#
#   ssh cairo-s101lp 'bash -s' < infra/cluster/feasibility/probe.sh > probe.out
#
# (on the VM as `sudo -u pruefstand ssh ...`). Nothing is written on the cluster (the model disk is
# nearly full, ADR-0019): no installs, no pulls, no server start or restart, no keep_alive change.
# The probe is READ-ONLY except one OPT-IN step: with MEASURE_LOAD=1 `model-load` sends one empty
# /api/generate that loads the generator (HTTP status, `error` field and /api/ps are checked, then the
# model is unloaded again with keep_alive 0); it runs only when /api/ps lists NO model, and
# only as an owner step under `pruefstand-lock` with MAINTENANCE set (nothing else may use the GPUs).
# Default: SKIP. PROBE_CHECKS="id id" limits the run to those checks (tests).
# Every check prints `CHECK <id> <PASS|FAIL|WARN> <detail>` on one line and never aborts the script.
# All code is inside functions and `main` runs with stdin from /dev/null, so no command can swallow
# the rest of the piped script. Env: MODELS_DIR (default /data/dheena/Models), GEN_MODEL, OLLAMA_URL,
# LOAD_TIMEOUT_S (default 900), PROBE_PROC_ROOT (default /proc, a test seam).
# A non-interactive ssh has a minimal PATH, so the Ollama binary is taken from the process that serves
# :11434 (fallback `command -v ollama`). Output shows it as `<ollama-bin>` and the home directory as
# `<home>`, so saved evidence never contains the binary path or the account name.
set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/data/dheena/Models}"
GEN_MODEL="${GEN_MODEL:-qwen3.8:27b-q8_0}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
PROC_ROOT="${PROBE_PROC_ROOT:-/proc}"
OLLAMA_BIN=""

redact() { # text -> text without the Ollama binary path and the home directory
  local s="$1" real
  if [ -n "$OLLAMA_BIN" ]; then s="${s//"$OLLAMA_BIN"/<ollama-bin>}"; fi
  if [ -n "${HOME:-}" ] && [ "$HOME" != / ]; then
    real="$(readlink -f "$HOME" 2>/dev/null || true)"
    s="${s//"$HOME"/<home>}"
    if [ -n "$real" ] && [ "$real" != / ]; then s="${s//"$real"/<home>}"; fi
  fi
  printf '%s' "$s"
}

emit() { # id status detail [max-length]
  local detail="${3//$'\n'/ }"
  detail="$(redact "$detail")"
  detail="$(tr -s ' ' <<<"$detail")"
  printf 'CHECK %s %s %s\n' "$1" "$2" "${detail:0:${4:-400}}"
}

have() { command -v "$1" >/dev/null 2>&1; }

check_os() {
  local pretty kernel
  # shellcheck disable=SC1091  # /etc/os-release is the target machine's file
  pretty="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}" || echo unknown)"
  kernel="$(uname -r)"
  if [ "$pretty" = unknown ]; then emit os WARN "no /etc/os-release, kernel $kernel"; else emit os PASS "$pretty, kernel $kernel"; fi
}

check_gpu() {
  if ! have nvidia-smi; then emit gpu FAIL "nvidia-smi not found"; return 0; fi
  local csv n a40 used
  csv="$(nvidia-smi --query-gpu=index,name,memory.total,memory.used,driver_version --format=csv,noheader 2>&1)" || {
    emit gpu FAIL "nvidia-smi failed: $csv"
    return 0
  }
  n="$(grep -c . <<<"$csv" || true)"
  a40="$(grep -c 'A40' <<<"$csv" || true)"
  used="$(awk -F', ' '{printf "%s%s", sep, $4; sep="/"}' <<<"$csv")"
  if [ "$n" -lt 2 ]; then
    emit gpu FAIL "$n GPU visible, need 2: $csv"
  elif [ "$a40" -lt 2 ]; then
    emit gpu WARN "$n GPUs but $a40 x A40; used $used; $csv"
  else
    emit gpu PASS "$a40 x A40, memory used $used, driver $(awk -F', ' 'NR==1{print $5}' <<<"$csv"), total $(awk -F', ' 'NR==1{print $3}' <<<"$csv") each"
  fi
}

check_gpu_procs() {
  local apps pid comm foreign="" listing=""
  have nvidia-smi || { emit gpu-procs WARN "nvidia-smi not found"; return 0; }
  apps="$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null || true)"
  if [ -z "$apps" ]; then emit gpu-procs PASS "no compute process visible (none, or owned by other users)"; return 0; fi
  while IFS=', ' read -r pid _; do
    comm="$(ps -o comm= -p "$pid" 2>/dev/null || echo unknown)"
    listing+="pid $pid=$comm; "
    case "$comm" in ollama*) ;; *) foreign="yes" ;; esac
  done <<<"$apps"
  if [ -n "$foreign" ]; then emit gpu-procs WARN "VRAM held by a non-ollama process: $listing"; else emit gpu-procs PASS "VRAM held by ollama only: $listing"; fi
}

listening_pids() { # pids that listen on :11434, from ss, lsof or fuser (whichever exists)
  if have ss; then
    ss -ltnp 2>/dev/null | grep -E '[:.]11434[[:space:]]' | grep -o 'pid=[0-9]*' | cut -d= -f2 || true
  fi
  if have lsof; then lsof -t -iTCP:11434 -sTCP:LISTEN 2>/dev/null || true; fi
  if have fuser; then fuser 11434/tcp 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true; fi
}

scan_serve_pids() { # own `ollama serve` processes found by scanning the proc tree
  local d args
  for d in "$PROC_ROOT"/[0-9]*; do
    [ -O "$d/cmdline" ] || continue
    args="$(tr '\0' ' ' <"$d/cmdline" 2>/dev/null || true)"
    case "$args" in *ollama\ serve*) basename "$d" ;; esac
  done
}

find_ollama_bin() { # path of the serving process's executable, else `command -v ollama`
  local pid exe
  for pid in $(listening_pids) $(scan_serve_pids); do
    exe="$(readlink -f "$PROC_ROOT/$pid/exe" 2>/dev/null || true)"
    exe="${exe% (deleted)}"
    if [ -n "$exe" ] && [ -x "$exe" ]; then printf '%s\n' "$exe"; return 0; fi
  done
  command -v ollama 2>/dev/null
}

check_ollama() {
  if [ -z "$OLLAMA_BIN" ]; then emit ollama FAIL "ollama binary not found"; return 0; fi
  emit ollama PASS "$OLLAMA_BIN: $("$OLLAMA_BIN" --version 2>&1 | head -2 | tr '\n' ' ')"
}

show_one() { # tag -> one-line metadata from `ollama show`
  local out arch params ctx quant lic
  out="$("$OLLAMA_BIN" show "$1" 2>&1 || true)"
  arch="$(awk '/^ +architecture/{print $2; exit}' <<<"$out")"
  params="$(awk '/^ +parameters/{print $2; exit}' <<<"$out")"
  ctx="$(awk '/^ +context length/{print $3; exit}' <<<"$out")"
  quant="$(awk '/^ +quantization/{print $2; exit}' <<<"$out")"
  lic="$(awk '/^ +License/{f=1; next} f && NF{print; exit}' <<<"$out" | sed 's/^ *//')"
  printf '%s [arch=%s params=%s ctx=%s quant=%s licence=%s]' "$1" "${arch:-?}" "${params:-?}" "${ctx:-?}" "${quant:-?}" "${lic:-?}"
}

check_ollama_list() {
  [ -n "$OLLAMA_BIN" ] || { emit ollama-list FAIL "ollama binary not found"; return 0; }
  OLLAMA_LIST="$("$OLLAMA_BIN" list 2>&1 || true)"
  local tags tag detail="" status=PASS arch
  tags="$(awk 'NR>1 && NF{print $1}' <<<"$OLLAMA_LIST")"
  for tag in $tags; do detail+="$(show_one "$tag"); "; done
  if ! grep -qx "$GEN_MODEL" <<<"$tags"; then
    status=WARN
    detail="$GEN_MODEL missing; $detail"
  else
    arch="$(show_one "$GEN_MODEL" | sed -n 's/.*arch=\([^ ]*\).*/\1/p')"
    case "$arch" in qwen*) ;; *) status=WARN; detail="$GEN_MODEL architecture $arch is not a Qwen one; $detail" ;; esac
  fi
  emit ollama-list "$status" "$detail" 900
}

check_ollama_store() {
  local pid env_dump want var got diffs="" shown="" dir
  pid="$(pgrep -u "$(id -u)" -f 'ollama serve' | head -1 || true)"
  if [ -z "$pid" ]; then emit ollama-store WARN "no own 'ollama serve' process found (system service or not running)"; return 0; fi
  env_dump="$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | grep -E '^(OLLAMA_|CUDA_VISIBLE_DEVICES)' || true)"
  for want in "OLLAMA_MODELS=$MODELS_DIR" OLLAMA_MAX_LOADED_MODELS=3 OLLAMA_NUM_PARALLEL=4 OLLAMA_KEEP_ALIVE=24h \
    OLLAMA_KV_CACHE_TYPE=q8_0 CUDA_VISIBLE_DEVICES=0,1; do
    var="${want%%=*}"
    got="$(grep -E "^${var}=" <<<"$env_dump" | head -1 | cut -d= -f2- || true)"
    shown+="${var}=${got:-unset} "
    if [ "$got" != "${want#*=}" ]; then diffs+="${var} is ${got:-unset} (expected ${want#*=}); "; fi
  done
  dir="$(grep -E '^OLLAMA_MODELS=' <<<"$env_dump" | head -1 | cut -d= -f2- || true)"
  if [ -z "$dir" ]; then diffs="model dir ~/.ollama/models (OLLAMA_MODELS unset); $diffs"; fi
  if grep -q '^OLLAMA_HOST=' <<<"$env_dump"; then shown+="OLLAMA_HOST=set "; else shown+="OLLAMA_HOST=unset "; fi
  shown+="pid=$pid"
  if [ -n "$diffs" ]; then emit ollama-store WARN "${diffs}[${shown}]" 600; else emit ollama-store PASS "$shown" 600; fi
}

check_ollama_provenance() {
  [ -n "$OLLAMA_BIN" ] || { emit ollama-provenance WARN "ollama binary not found"; return 0; }
  local from name tag path code
  from="$("$OLLAMA_BIN" show --modelfile "$GEN_MODEL" 2>&1 | grep -m1 '^FROM' | sed -E 's#^FROM .*/(sha256-[0-9a-f]{12})[0-9a-f]*$#FROM blob \1...#' || true)"
  name="${GEN_MODEL%%:*}"
  tag="${GEN_MODEL#*:}"
  path="$name"
  case "$name" in */*) ;; *) path="library/$name" ;; esac
  have curl || { emit ollama-provenance WARN "curl missing, registry not probed; ${from:-no FROM line}"; return 0; }
  code="$(curl -sS -o /dev/null -m 20 -w '%{http_code}' "https://registry.ollama.ai/v2/$path/manifests/$tag" 2>/dev/null || true)"
  case "$code" in
    200) emit ollama-provenance PASS "registry has $GEN_MODEL (HTTP 200); ${from:-no FROM line}" ;;
    404) emit ollama-provenance WARN "local-only tag: copy blobs + manifest over SSH to the VM data root backups/models/ (T3.1a S2b); registry HTTP 404; ${from:-no FROM line}" ;;
    *) emit ollama-provenance WARN "registry not reachable (HTTP ${code:-000}), provenance unknown; ${from:-no FROM line}" ;;
  esac
}

check_port() {
  local listeners serving="" line pid args svc
  listeners="$(ss -ltnp 2>/dev/null | grep -E '[:.]11434[[:space:]]' || true)"
  if [ -z "$listeners" ]; then emit port-11434 FAIL "nothing listens on :11434"; return 0; fi
  for pid in $(ss -ltnp 2>/dev/null | grep '"ollama"' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    args="$(ps -o args= -p "$pid" 2>/dev/null || true)"
    case "$args" in *" serve"*) serving+="$pid " ;; esac
  done
  svc="$(systemctl is-active ollama 2>/dev/null || true)"
  line="$(head -1 <<<"$listeners")"
  if [ "$svc" = active ]; then
    emit port-11434 WARN "port held by system ollama.service (active): reuse it only if it serves $MODELS_DIR from the owner's start script, else the admin stops it or we pick a free port in .env + docker.md 3"
  elif ! grep -q 'users:' <<<"$line"; then
    emit port-11434 WARN "port held by another user (no process info): reuse it only if it serves $MODELS_DIR, else the admin stops it or we pick a free port"
  elif [ "$(wc -w <<<"$serving")" -gt 1 ]; then
    emit port-11434 WARN "second listening Ollama serve process(es): $serving"
  else
    emit port-11434 PASS "held by the cluster user's own ollama serve (pid ${serving:-?}); the server we reuse (ADR-0018)"
  fi
}

check_logind() {
  local user linger kup
  user="${USER:-$(id -un)}"
  linger="$(loginctl show-user "$user" -p Linger 2>/dev/null | cut -d= -f2 || true)"
  kup="$(grep -rhiE '^[[:space:]]*KillUserProcesses' /etc/systemd/logind.conf /etc/systemd/logind.conf.d/ 2>/dev/null | tail -1 | cut -d= -f2 | tr -d ' ' || true)"
  kup="${kup:-no (unset in logind.conf; systemd default)}"
  case "$kup" in
    yes) emit logind WARN "Linger=${linger:-unknown} KillUserProcesses=yes" ;;
    *) emit logind PASS "Linger=${linger:-unknown} KillUserProcesses=${kup%% *}" ;;
  esac
}

check_tmux() {
  if have tmux; then emit tmux PASS "tmux present (not used for serving, Y5.4)"; else emit tmux PASS "tmux absent (not needed, Y5.4)"; fi
}

check_models_space() {
  local avail_kb tenths need_tenths=20 missing="" used
  avail_kb="$(df -k --output=avail "$MODELS_DIR" 2>/dev/null | tail -1 | tr -d ' ' || true)"
  if ! [[ "$avail_kb" =~ ^[0-9]+$ ]]; then emit models-space FAIL "cannot read free space of $MODELS_DIR"; return 0; fi
  tenths=$((avail_kb * 1024 / 100000000))
  if ! grep -q '^bge-m3' <<<"${OLLAMA_LIST:-}"; then need_tenths=$((need_tenths + 12)); missing+="bge-m3 "; fi
  if ! grep -q '^gemma3:12b' <<<"${OLLAMA_LIST:-}"; then need_tenths=$((need_tenths + 80)); missing+="gemma3:12b "; fi
  used="$(du -sh "$MODELS_DIR" 2>/dev/null | cut -f1 || true)"
  local msg="$((tenths / 10)).$((tenths % 10)) GB free on $MODELS_DIR (models ${used:-?}); need $((need_tenths / 10)).$((need_tenths % 10)) GB incl. 2.0 GB reserve, pending pulls: ${missing:-none}"
  if [ "$tenths" -lt $((need_tenths - 2)) ]; then emit models-space FAIL "$msg"
  elif [ "$tenths" -lt $((need_tenths + 8)) ]; then emit models-space WARN "$msg"
  else emit models-space PASS "$msg"; fi
}

check_model_load() {
  if [ "${MEASURE_LOAD:-0}" != 1 ]; then
    emit model-load PASS "SKIP: cold load not measured; opt-in MEASURE_LOAD=1, an owner step under pruefstand-lock and MAINTENANCE"
    return 0
  fi
  have curl || { emit model-load WARN "curl missing, not measuring"; return 0; }
  local ps_out t0 t1 secs resp rc=0 code body err note=""
  ps_out="$(curl -fsS -m 10 "$OLLAMA_URL/api/ps" 2>/dev/null || true)"
  if ! grep -q '"models"' <<<"$ps_out"; then
    emit model-load WARN "cannot read a valid /api/ps answer, not measuring"
    return 0
  fi
  if grep -q '"name"' <<<"$ps_out"; then
    emit model-load PASS "SKIP: a model is loaded ($(grep -o '"name":"[^"]*"' <<<"$ps_out" | cut -d'"' -f4 | tr '\n' ' ')); unload it first, then rerun"
    return 0
  fi
  t0="$(date +%s%N)"
  resp="$(curl -sS -m "${LOAD_TIMEOUT_S:-900}" -w $'\n%{http_code}' "$OLLAMA_URL/api/generate" \
    -d "{\"model\":\"$GEN_MODEL\",\"prompt\":\"\",\"keep_alive\":\"5m\",\"stream\":false}" 2>&1)" || rc=$?
  t1="$(date +%s%N)"
  if [ "$rc" -ne 0 ]; then
    emit model-load FAIL "load request failed (curl exit $rc): ${resp//$'\n'/ }" 300
    return 0
  fi
  code="${resp##*$'\n'}"
  body="${resp%$'\n'*}"
  err="$(sed -n 's/.*"error" *: *"\([^"]*\)".*/\1/p' <<<"$body" | head -1)"
  if ! [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
    emit model-load FAIL "load request answered HTTP ${code:-?}: ${err:-$body}" 300
    return 0
  fi
  if grep -q '"error"' <<<"$body"; then
    emit model-load FAIL "load request returned an error: ${err:-$body}" 300
    return 0
  fi
  ps_out="$(curl -fsS -m 10 "$OLLAMA_URL/api/ps" 2>/dev/null || true)"
  if ! grep -qF "\"$GEN_MODEL\"" <<<"$ps_out"; then
    emit model-load FAIL "load request answered HTTP $code but $GEN_MODEL is not listed as loaded by /api/ps" 300
    return 0
  fi
  curl -sS -m 60 -o /dev/null "$OLLAMA_URL/api/generate" \
    -d "{\"model\":\"$GEN_MODEL\",\"prompt\":\"\",\"keep_alive\":0,\"stream\":false}" 2>/dev/null || note="; unloading afterwards failed, unload by hand"
  secs=$(((t1 - t0) / 1000000000))
  if [ "$secs" -gt 300 ] || [ -n "$note" ]; then
    emit model-load WARN "cold load $((secs / 60)).$(((secs % 60) * 10 / 60)) min ($secs s) from $MODELS_DIR$note"
  else
    emit model-load PASS "cold load $((secs / 60)).$(((secs % 60) * 10 / 60)) min ($secs s) from $MODELS_DIR"
  fi
}

check_local_disk() {
  emit local-disk PASS "$(df -h / /data 2>/dev/null | awk 'NR>1{printf "%s avail %s of %s; ", $6, $4, $2}')"
}

check_net() {
  have curl || { emit net FAIL "curl missing"; return 0; }
  local base man hf
  base="$(curl -sS -o /dev/null -m 20 -w '%{http_code}' https://registry.ollama.ai/v2/ 2>/dev/null || true)"
  man="$(curl -sS -o /dev/null -m 20 -w '%{http_code}' https://registry.ollama.ai/v2/library/gemma3/manifests/12b 2>/dev/null || true)"
  hf="$(curl -sS -o /dev/null -m 20 -w '%{http_code}' https://huggingface.co 2>/dev/null || true)"
  base="${base:-000}"; man="${man:-000}"; hf="${hf:-000}"
  local msg="registry.ollama.ai /v2/ HTTP $base, gemma3:12b manifest HTTP $man; huggingface.co HTTP $hf"
  if [ "$man" = 200 ]; then
    if [ "$hf" = 000 ]; then emit net WARN "$msg (huggingface.co unreachable)"; else emit net PASS "$msg"; fi
  elif [ "$base" != 000 ] && [ "${base:0:1}" != 5 ]; then
    emit net WARN "$msg (registry answers but the manifest is not 200)"
  else
    emit net FAIL "$msg (pulls impossible)"
  fi
}

check_docker() {
  local found="" c
  for c in docker podman apptainer; do have "$c" && found+="$c "; done
  if [ -n "$found" ]; then emit docker PASS "present: $found"; else emit docker PASS "docker/podman/apptainer absent (assumed, Z1)"; fi
}

check_vllm() {
  if have vllm; then emit vllm PASS "vllm present: $(command -v vllm)"; else emit vllm PASS "vllm absent (assumed, Z1)"; fi
}

run_check() { "$1" || emit "${1#check_}" WARN "check function failed unexpectedly"; }

main() {
  OLLAMA_LIST=""
  OLLAMA_BIN="$(find_ollama_bin || true)"
  redact "# probe $(date -u +%FT%TZ) MODELS_DIR=$MODELS_DIR GEN_MODEL=$GEN_MODEL"
  echo
  local c name wanted="${PROBE_CHECKS:-}"
  for c in check_os check_gpu check_gpu_procs check_ollama check_ollama_list check_ollama_store \
    check_ollama_provenance check_port check_logind check_tmux check_models_space check_model_load \
    check_local_disk check_net check_docker check_vllm; do
    name="${c#check_}"
    name="${name//_/-}"
    if [ -z "$wanted" ] || [[ " $wanted " == *" $name "* ]]; then run_check "$c"; fi
  done
}

main </dev/null
