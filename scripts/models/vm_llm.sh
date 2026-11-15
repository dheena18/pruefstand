#!/usr/bin/env bash
# vm_llm.sh start [14b|8b] | stop | status | print-cmd [14b|8b]: the on-demand CPU datagen model on the VM (D1200).
# Default 14b (Ministral 3 14B, the D1200 pick: same cost per valid in-domain item as 8b, better quality).
#
# Runs the pinned llama.cpp `llama-server` (copied out of the pinned image, $VM_LLM_BIN_DIR) with an official Mistral
# GGUF (Ministral 3, Apache-2.0) as the owner user. Owner rules (D1200): bound to 127.0.0.1 only (never reachable from
# gate-net or another host, D850), at most VM_LLM_MAX_THREADS (80, half of the 160 vCPUs) threads, pinned to
# $VM_LLM_CPUS with taskset, nice 15 / ionice idle, started on demand and stopped after (hard stop after
# $VM_LLM_MAX_MIN minutes), and never while a gate run or a `make check-vm` runs: the server holds the host lock
# (`pruefstand-lock`, gpu.lock) AND every check slot of scripts/vm_check.sh for its whole life, so a gate job or a
# check waits for it to stop, and it refuses to start while either is busy.
#   start  exit 0 ready; 75 gpu.lock or a check slot busy; 2 usage/config; 1 the server did not come up
#   stop   exit 0 (also when nothing runs)
#   status exit 0 running (prints the base URL), 3 stopped
# The base URL for clients is printed by `start`/`status`: http://127.0.0.1:$VM_LLM_PORT/v1; the served model id
# (alias) is the model part of the pinned id, e.g. openai_compatible_local/ministral-3-14b-instruct-2512 (D1201).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
models_dir="${VM_LLM_MODELS_DIR:-$HOME/.cache/pruefstand/models}"
bin_dir="${VM_LLM_BIN_DIR:-$HOME/.local/llama-cpp/app}"
state="${VM_LLM_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/pruefstand-vm-llm}"
port="${VM_LLM_PORT:-18091}"
threads="${VM_LLM_THREADS:-16}"
cpus="${VM_LLM_CPUS:-0-19}"
ctx="${VM_LLM_CTX:-8192}"
max_min="${VM_LLM_MAX_MIN:-240}"
ready_s="${VM_LLM_READY_S:-240}"
lock_cmd="${VM_LLM_LOCK_CMD:-pruefstand-lock}"
check_dir="${PRUEFSTAND_CHECK_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/pruefstand-check}"
check_slots="${PRUEFSTAND_CHECK_SLOTS:-2}"
MAX_THREADS=80
DEFAULT_MODEL=14b

die() { echo "vm_llm: $2" >&2; exit "$1"; }

# name -> "file size sha256 alias" (official mistralai/Ministral-3-*-Instruct-2512-GGUF, Q4_K_M; revisions in D1200)
model_spec() {
  case "$1" in
    8b) echo "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf 5198911904 33e7a72cf5e6e2cfc2f2847075acc013d68bba023e35310cef86b5cf8fdca761 ministral-3-8b-instruct-2512" ;;
    14b) echo "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf 8239593024 824e0f3373e69b84f2cae46fdcb9bd1ebc6ab3bfc7acc125d818b7b8178cc613 ministral-3-14b-instruct-2512" ;;
    *) return 1 ;;
  esac
}

is_uint() { case "$1" in '' | *[!0-9]*) return 1 ;; *) return 0 ;; esac; }

validate() {
  model_spec "$1" > /dev/null || die 2 "unknown model '$1' (8b or 14b)"
  for v in port threads ctx max_min ready_s check_slots; do
    is_uint "${!v}" || die 2 "$v must be a whole number (got '${!v}')"
  done
  [ "$threads" -ge 1 ] && [ "$threads" -le "$MAX_THREADS" ] \
    || die 2 "VM_LLM_THREADS must be 1..$MAX_THREADS (at most half the vCPUs, D1200), got $threads"
  [[ "$cpus" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || die 2 "VM_LLM_CPUS must be a cpu list like 0-19"
  [ "$max_min" -ge 1 ] || die 2 "VM_LLM_MAX_MIN must be at least 1"
}

# The exact server command (no lock, no checks); one word per line for print-cmd.
server_cmd() {
  local file size sha alias
  read -r file size sha alias <<< "$(model_spec "$1")"
  printf '%s\n' timeout --signal=TERM --kill-after=30 "${max_min}m" nice -n 15 ionice -c3 taskset -c "$cpus" \
    "$bin_dir/llama-server" -m "$models_dir/$file" --alias "$alias" -t "$threads" -c "$ctx" -np 1 --jinja --no-webui \
    --host 127.0.0.1 --port "$port"
}

pid_alive() { [ -f "$state/pid" ] && kill -0 "$(cat "$state/pid")" 2> /dev/null; }

verify_model() {
  local file size sha alias path stamp
  read -r file size sha alias <<< "$(model_spec "$1")"
  path="$models_dir/$file"
  [ -f "$path" ] || die 2 "model file missing: $path (download it and check its SHA-256, D1200)"
  [ "$(stat -c %s "$path")" = "$size" ] || die 2 "$file has the wrong size (expected $size bytes)"
  stamp="$size $(stat -c %Y "$path") $sha"
  if [ "$(cat "$state/verified-$1" 2> /dev/null)" != "$stamp" ]; then
    echo "vm_llm: checking the SHA-256 of $file (once per file version)" >&2
    [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$sha" ] || die 2 "$file: SHA-256 mismatch"
    echo "$stamp" > "$state/verified-$1"
  fi
}

# Runs under the lock: take every check slot (kept open, so the server holds them), verify, exec the server.
serve() {
  local i fd cmd
  mkdir -p "$check_dir"
  for ((i = 1; i <= check_slots; i++)); do
    exec {fd}> "$check_dir/slot$i.lock"
    flock -n "$fd" || die 75 "check slot $i is busy (a make check-vm runs); start again after it ends"
  done
  verify_model "$1"
  echo $$ > "$state/pid"
  mapfile -t cmd < <(server_cmd "$1")
  LD_LIBRARY_PATH="$bin_dir" exec "${cmd[@]}"
}

start() {
  local model=$1 i rc
  validate "$model"
  mkdir -p "$state"
  if pid_alive; then die 2 "already running (pid $(cat "$state/pid")); run '$0 stop' first"; fi
  rm -f "$state/pid"
  if (exec 3<> "/dev/tcp/127.0.0.1/$port") 2> /dev/null; then die 2 "port $port is already in use"; fi
  : > "$state/log"
  GPU_LOCK_TIMEOUT_S="${VM_LLM_LOCK_WAIT_S:-5}" setsid "$lock_cmd" bash "$here/vm_llm.sh" _serve "$model" \
    >> "$state/log" 2>&1 < /dev/null &
  local launcher=$!
  for ((i = 0; i < ready_s; i++)); do
    if curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
      echo "vm_llm: $model ready at http://127.0.0.1:$port/v1 (pid $(cat "$state/pid"), stops after ${max_min} min)"
      return 0
    fi
    if ! kill -0 "$launcher" 2> /dev/null; then
      rc=0
      wait "$launcher" || rc=$?
      tail -n 5 "$state/log" >&2
      rm -f "$state/pid"
      [ "$rc" -eq 75 ] && die 75 "not started: gpu.lock or a check slot is busy (gate run or check)"
      die 1 "the server exited (exit $rc) before it was ready; log: $state/log"
    fi
    sleep 1
  done
  stop > /dev/null
  die 1 "not ready after ${ready_s}s; stopped (log: $state/log)"
}

stop() {
  local pid pgid i
  if ! pid_alive; then
    rm -f "$state/pid"
    echo "vm_llm: not running"
    return 0
  fi
  pid="$(cat "$state/pid")"
  pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  kill -TERM -- "-$pgid" 2> /dev/null || kill -TERM "$pid"
  for ((i = 0; i < 30; i++)); do
    kill -0 "$pid" 2> /dev/null || break
    sleep 1
  done
  kill -KILL -- "-$pgid" 2> /dev/null || true
  rm -f "$state/pid"
  echo "vm_llm: stopped"
}

status() {
  if pid_alive; then
    echo "vm_llm: running (pid $(cat "$state/pid")) at http://127.0.0.1:$port/v1"
    return 0
  fi
  echo "vm_llm: stopped"
  return 3
}

case "${1:-}" in
  start) start "${2:-${VM_LLM_MODEL:-$DEFAULT_MODEL}}" ;;
  stop) stop ;;
  status) status ;;
  print-cmd)
    validate "${2:-${VM_LLM_MODEL:-$DEFAULT_MODEL}}"
    server_cmd "${2:-${VM_LLM_MODEL:-$DEFAULT_MODEL}}"
    ;;
  _serve) serve "$2" ;;
  *) die 2 "usage: vm_llm.sh start [14b|8b] | stop | status | print-cmd [14b|8b]" ;;
esac
