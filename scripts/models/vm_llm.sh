#!/usr/bin/env bash
# vm_llm.sh start [14b|8b] | stop | status | print-cmd [14b|8b]: the on-demand CPU datagen model on the VM (D1200).
# Default 14b (Ministral 3 14B, the D1200 pick: same cost per valid in-domain item as 8b, better quality).
#
# Runs the pinned llama.cpp `llama-server` (copied out of the pinned image, $VM_LLM_BIN_DIR) with an official Mistral
# GGUF (Ministral 3, Apache-2.0) as the owner user. Owner rules (D1200): bound to 127.0.0.1 only (never reachable from
# gate-net or another host, D850; the local API itself is unauthenticated), at most VM_LLM_MAX_THREADS (80, half of the
# 160 vCPUs) threads, pinned to $VM_LLM_CPUS with taskset, nice 15 / ionice idle, started on demand and stopped after
# (hard stop after $VM_LLM_MAX_MIN minutes), and never while a gate run or a `make check-vm` runs: the server holds the
# host lock (`pruefstand-lock`, gpu.lock) AND every check slot of scripts/vm_check.sh for its whole life, so a gate job
# or a check waits for it to stop, and it refuses to start while either is busy.
#   start  exit 0 ready; 75 MAINTENANCE set, gpu.lock or a check slot busy; 2 usage/config/model file; 1 the server
#          did not come up
#   stop   exit 0 (also when nothing runs), 2 when the PID file names a live server on another VM_LLM_PORT;
#          waits for a start that is still running (up to VM_LLM_READY_S + 90 s)
#   status exit 0 running (prints the base URL), 3 stopped
# The base URL for clients is printed by `start`/`status`: http://127.0.0.1:$VM_LLM_PORT/v1; the served model id
# (alias) is the model part of the pinned id, e.g. openai_compatible_local/ministral-3-14b-instruct-2512 (D1201).
# PID safety: the PID file holds "pid starttime token"; nothing is signalled unless /proc/<pid> still is that process
# (same start time, cmdline with llama-server and our port). start and stop serialise on $state/start.lock.
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
# Directory of gpu.lock and MAINTENANCE (as fetch-model.sh / gate_orchestrator.lock); tests point it at a temp dir.
lock_dir="${PRUEFSTAND_LOCK_DIR:-/var/lib/pruefstand}"
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
  model_spec "$1" > /dev/null || die 2 "unknown model '$1' (14b or 8b)"
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
    --no-slots --host 127.0.0.1 --port "$port"
}

# Field 22 of /proc/<pid>/stat (start time in clock ticks); the comm field may hold spaces, so cut after ')'.
start_time() {
  local s f
  s="$(cat "/proc/$1/stat" 2> /dev/null)" || return 1
  read -r -a f <<< "${s##*) }" # fields 3.. of stat; field 22 is f[19]
  echo "${f[19]}"
}

# True only when the PID file names a live process that is still our server: positive pid, same start time,
# cmdline with llama-server and our port. Prints the pid.
our_server() {
  local pid st token cmd
  [ -f "$state/pid" ] || return 1
  read -r pid st token < "$state/pid" || return 1
  [[ "${pid:-}" =~ ^[1-9][0-9]*$ ]] || return 1
  is_uint "${st:-}" || return 1
  [ "$(start_time "$pid")" = "$st" ] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2> /dev/null)" || return 1
  [[ "$cmd" == *llama-server* && "$cmd" == *"--port $port "* ]] || return 1
  echo "$pid"
}

# A PID file is stale when its process is gone: bad content, dead pid, or another start time. A live
# process with the recorded start time is kept even when it is not ours on THIS port (a server started
# with another VM_LLM_PORT must not be orphaned by a stop/status with the default port).
pid_file_stale() {
  local pid st _t
  read -r pid st _t 2> /dev/null < "$state/pid" || return 0
  [[ "${pid:-}" =~ ^[1-9][0-9]*$ ]] || return 0
  is_uint "${st:-}" || return 0
  [ "$(start_time "$pid")" != "$st" ]
}

# Callers hold start.lock.
drop_stale() { if [ -f "$state/pid" ] && pid_file_stale; then rm -f "$state/pid"; fi; }

# The launcher (pruefstand-lock -> flock -> _serve) is a session leader (setsid): its group holds the
# whole chain while _serve waits for the lock or hashes the model. $state/launcher = "pid starttime token".
# Identity = pid + start time + this start's token (the command line changes along the exec chain).
launcher_alive() {
  local pid st t
  read -r pid st t 2> /dev/null < "$state/launcher" || return 1
  [[ "${pid:-}" =~ ^[1-9][0-9]*$ ]] || return 1
  [ "${t:-}" = "$1" ] || return 1
  [ "$(start_time "$pid")" = "$st" ] || return 1
  echo "$pid"
}

# Stop a launcher that has not become a ready server (start timed out): TERM its group (identity checked
# once), wait until NO group member is left (kill -0 on the group, at most 30 s), then KILL the group and
# wait at most 5 s more. Never waits unboundedly.
kill_launcher() {
  local pid i
  if pid="$(launcher_alive "$1")"; then
    kill -TERM -- "-$pid" 2> /dev/null || true
    for ((i = 0; i < 30; i++)); do
      kill -0 -- "-$pid" 2> /dev/null || break
      sleep 1
    done
    kill -KILL -- "-$pid" 2> /dev/null || true
    for ((i = 0; i < 5; i++)); do
      kill -0 -- "-$pid" 2> /dev/null || break
      sleep 1
    done
  fi
  rm -f "$state/launcher"
}

verify_model() {
  local file size sha alias path real stamp
  read -r file size sha alias <<< "$(model_spec "$1")"
  path="$models_dir/$file"
  [ -f "$path" ] || die 2 "model file missing: $path (download it and check its SHA-256, D1200)"
  real="$(readlink -f "$path")"
  [ "$real" = "$path" ] || echo "vm_llm: $file is a symlink to $real; checking the target" >&2
  [ "$(stat -L -c %s "$path")" = "$size" ] || die 2 "$file has the wrong size (expected $size bytes)"
  stamp="$(stat -L -c '%s %Y %i %Z' "$path") $sha"
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
  echo "$$ $(start_time $$) ${VM_LLM_TOKEN:?}" > "$state/pid"
  mapfile -t cmd < <(server_cmd "$1")
  LD_LIBRARY_PATH="$bin_dir" exec "${cmd[@]}"
}

# fd 8 = $state/start.lock for the whole of start/stop; never inherited by the server (8>&- on the spawn).
take_start_lock() {
  mkdir -p "$state"
  exec 8> "$state/start.lock"
  flock -w "$1" 8 || die 75 "another vm_llm.sh start/stop holds $state/start.lock"
}

# Remove the PID file only when it carries this invocation's token.
drop_own_pid() { local _p _s t; read -r _p _s t 2> /dev/null < "$state/pid" && [ "${t:-}" = "$1" ] && rm -f "$state/pid"; return 0; }

start() {
  local model=$1 i rc token launcher
  validate "$model"
  # A model swap is running (gpu-cluster.md section 8): never start then (read-only existence test, D1285).
  [ ! -e "$lock_dir/MAINTENANCE" ] || die 75 "MAINTENANCE is set (a model swap is running): refused"
  take_start_lock "${VM_LLM_START_WAIT_S:-10}"
  drop_stale
  if our_server > /dev/null; then die 2 "already running (pid $(our_server)); run '$0 stop' first"; fi
  if (exec 3<> "/dev/tcp/127.0.0.1/$port") 2> /dev/null; then die 2 "port $port is already in use"; fi
  token="$$-$RANDOM$RANDOM"
  : > "$state/log"
  env -u PRUEFSTAND_LOCK_HELD GPU_LOCK_TIMEOUT_S="${VM_LLM_LOCK_WAIT_S:-5}" VM_LLM_TOKEN="$token" \
    setsid "$lock_cmd" bash "$here/vm_llm.sh" _serve "$model" >> "$state/log" 2>&1 < /dev/null 8>&- &
  launcher=$!
  [ "$(ps -o pgid= -p "$launcher" | tr -d ' ')" = "$launcher" ] || echo "vm_llm: warning: launcher is not a group leader" >&2
  echo "$launcher $(start_time "$launcher") $token" > "$state/launcher"
  for ((i = 0; i < ready_s; i++)); do
    if our_server > /dev/null && curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/health"; then
      echo "vm_llm: $model ready at http://127.0.0.1:$port/v1 (pid $(our_server), stops after ${max_min} min)"
      rm -f "$state/launcher"
      return 0
    fi
    if ! kill -0 "$launcher" 2> /dev/null; then
      rc=0
      wait "$launcher" || rc=$?
      tail -n 5 "$state/log" >&2
      rm -f "$state/launcher"
      drop_own_pid "$token"
      [ "$rc" -eq 75 ] && die 75 "not started: gpu.lock or a check slot is busy (gate run or check)"
      [ "$rc" -eq 2 ] && die 2 "not started: configuration or model file error (log: $state/log)"
      die 1 "the server exited (exit $rc) before it was ready; log: $state/log"
    fi
    sleep 1
  done
  stop_locked > /dev/null 2>&1 || true
  kill_launcher "$token" # still waiting for the lock or hashing: it must not become a server later
  kill -0 "$launcher" 2> /dev/null || wait "$launcher" 2> /dev/null || true # reap only a dead child
  drop_own_pid "$token"
  die 1 "not ready after ${ready_s}s; stopped (log: $state/log)"
}

# Caller holds start.lock. Signals only a process whose identity matches (our_server), never a process group.
stop_locked() {
  local pid i
  if ! pid="$(our_server)"; then
    if [ -f "$state/pid" ] && ! pid_file_stale; then
      echo "vm_llm: pid $(cut -d' ' -f1 < "$state/pid") is a server on another VM_LLM_PORT; stop it with that port" >&2
      return 2
    fi
    rm -f "$state/pid"
    echo "vm_llm: not running"
    return 0
  fi
  # timeout (uutils coreutils on the VM, GNU elsewhere) forwards TERM to llama-server; --kill-after=30 KILLs it
  kill -TERM "$pid" 2> /dev/null || true
  for ((i = 0; i < 40; i++)); do
    our_server > /dev/null || break
    sleep 1
  done
  if pid="$(our_server)"; then kill -KILL "$pid" 2> /dev/null || true; fi
  rm -f "$state/pid"
  echo "vm_llm: stopped"
}

stop() {
  take_start_lock "${VM_LLM_STOP_WAIT_S:-$((ready_s + 90))}" # a start (up to ready_s + ~70 s) finishes first
  stop_locked
}

status() {
  local pid
  mkdir -p "$state"
  exec 8> "$state/start.lock"
  if flock -n 8; then drop_stale; fi # never clean up under a running start
  if pid="$(our_server)"; then
    echo "vm_llm: running (pid $pid) at http://127.0.0.1:$port/v1"
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
