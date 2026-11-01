#!/usr/bin/env bash
# T0.6 S2: Ollama API checks through the SSH tunnel, run on the VM or WSL (NOT on the cluster).
#
#   tunnel_check.sh [--use-existing-tunnel] [--print-cmd]
#
# --use-existing-tunnel  probe http://127.0.0.1:11434 (pruefstand-tunnel.service) and open no forward.
# --print-cmd            print the SSH commands and the API base URL, run nothing (unit test).
# Env: PROBE_PORT0 (temporary local port, default 21434, never 11434), CLUSTER_ALIAS (default
#      cairo-s101lp), GEN_MODEL (default qwen3.8:27b-q8_0), EMBED_MODEL (default bge-m3).
# Output: `CHECK <id> <PASS|FAIL|WARN> <detail>` lines. Never pulls, never loads another model
# (bge-m3 is only called when `/api/tags` lists it), never changes keep_alive. ADR-0018: one forward.
set -euo pipefail

ALIAS="${CLUSTER_ALIAS:-cairo-s101lp}"
GEN_MODEL="${GEN_MODEL:-qwen3.8:27b-q8_0}"
EMBED_MODEL="${EMBED_MODEL:-bge-m3}"
GEN_DIGEST="8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039"
PORT0="${PROBE_PORT0:-21434}"
EXISTING=0
PRINT=0

for arg in "$@"; do
  case "$arg" in
    --use-existing-tunnel) EXISTING=1 ;;
    --print-cmd) PRINT=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ "$PORT0" = "11434" ]; then
  echo "PROBE_PORT0 must not be 11434 (that port belongs to pruefstand-tunnel.service)" >&2
  exit 2
fi

if [ "$EXISTING" = 1 ]; then
  BASE="http://127.0.0.1:11434"
else
  BASE="http://127.0.0.1:${PORT0}"
fi
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20)
FORWARD_CMD=(ssh -N -o ExitOnForwardFailure=yes -L "127.0.0.1:${PORT0}:localhost:11434" "$ALIAS")
START_REMOTE='setsid nohup sleep 900 >/dev/null 2>&1 < /dev/null & echo $!'

live_remote() { # $1 = pid; kill only a process that is still our `sleep`
  # shellcheck disable=SC2016  # the $(...) must reach the cluster shell unexpanded
  printf 'kill -0 %s && [ "$(ps -o comm= -p %s)" = sleep ] && kill %s && echo alive' "$1" "$1" "$1"
}

if [ "$PRINT" = 1 ]; then
  echo "API: $BASE"
  if [ "$EXISTING" = 0 ]; then
    echo "${FORWARD_CMD[*]}"
  fi
  echo "ssh ${SSH_OPTS[*]} $ALIAS '$START_REMOTE'"
  echo "ssh ${SSH_OPTS[*]} $ALIAS '$(live_remote '<pid>')'"
  exit 0
fi

emit() { # id status detail
  local detail="${3//$'\n'/ }"
  printf 'CHECK %s %s %s\n' "$1" "$2" "${detail:0:400}"
}

TMP="$(mktemp -d)"
FWD_PID=""
cleanup() {
  if [ -n "$FWD_PID" ]; then kill "$FWD_PID" 2>/dev/null || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

http() { # method path [json-file]; body to $TMP/body, prints the HTTP code
  local method="$1" path="$2" data="${3:-}"
  local args=(-sS --max-time 900 -o "$TMP/body" -w '%{http_code}' -X "$method" "$BASE$path")
  if [ -n "$data" ]; then args+=(-H 'Content-Type: application/json' --data-binary "@$data"); fi
  local code
  code="$(curl "${args[@]}" 2>"$TMP/err")" || true
  echo "${code:-000}"
}

port_busy() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }

check_fwd() {
  if [ "$EXISTING" = 1 ]; then
    emit fwd PASS "existing tunnel ($BASE)"
    return 0
  fi
  if port_busy "$PORT0"; then
    emit fwd FAIL "local port $PORT0 in use (set PROBE_PORT0)"
    return 1
  fi
  "${FORWARD_CMD[@]}" >"$TMP/fwd.log" 2>&1 &
  FWD_PID=$!
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "$FWD_PID" 2>/dev/null; then break; fi
    if port_busy "$PORT0"; then
      emit fwd PASS "forward 127.0.0.1:$PORT0 -> cluster localhost:11434 opened"
      return 0
    fi
    sleep 1
  done
  FWD_PID=""
  emit fwd FAIL "port forwarding failed: $(head -c 200 "$TMP/fwd.log")"
  return 1
}

check_tags() {
  local code
  code="$(http GET /api/tags)"
  if [ "$code" != 200 ]; then
    emit api-tags FAIL "GET /api/tags -> HTTP $code"
    return 0
  fi
  if ! jq -e --arg m "$GEN_MODEL" '.models[] | select(.name == $m)' "$TMP/body" >"$TMP/model.json"; then
    emit api-tags WARN "200 but $GEN_MODEL not listed"
    return 0
  fi
  local digest
  digest="$(jq -r '.digest' "$TMP/model.json")"
  if [ "$digest" = "$GEN_DIGEST" ]; then
    emit api-tags PASS "200, $GEN_MODEL digest ${digest:0:12} matches setup log 3"
  else
    emit api-tags WARN "200, $GEN_MODEL digest ${digest:0:12} differs from setup log 3"
  fi
}

check_chat() {
  jq -n --arg m "$GEN_MODEL" '{model:$m, think:false, stream:false, options:{num_ctx:8192, num_predict:64},
    messages:[{role:"user", content:"Sag in einem Satz Hallo."}]}' >"$TMP/req.json"
  local code
  code="$(http POST /api/chat "$TMP/req.json")"
  if [ "$code" != 200 ]; then
    emit api-chat-nothink FAIL "POST /api/chat -> HTTP $code $(head -c 150 "$TMP/body")"
    return 0
  fi
  local content thinking
  content="$(jq -r '.message.content // ""' "$TMP/body")"
  thinking="$(jq -r '.message.thinking // ""' "$TMP/body")"
  if [ -n "$thinking" ] || [[ "$content" == *"<think>"* ]]; then
    emit api-chat-nothink FAIL "thinking content present despite think:false"
  elif [ -z "$content" ]; then
    emit api-chat-nothink FAIL "empty answer"
  elif grep -qiE 'hallo|guten|grüß|servus|moin|willkommen' <<<"$content"; then
    emit api-chat-nothink PASS "German answer, no thinking: ${content:0:80}"
  else
    emit api-chat-nothink WARN "no thinking, but not recognisably German: ${content:0:80}"
  fi
}

long_prompt() { # a unique nonce first, so a prompt cache of an earlier run cannot lower the count
  local i
  printf 'Lauf %s.\n' "$(date +%s%N)"
  for i in $(seq 1 220); do
    printf 'Der Mieter kann das Mietverhältnis nach § 573 BGB nur kündigen, wenn er ein berechtigtes Interesse hat (Satz %s).\n' "$i"
  done
  printf 'Fasse den Text in einem Wort zusammen.\n'
}

check_ctx() {
  jq -n --arg m "$GEN_MODEL" --arg p "$(long_prompt)" '{model:$m, think:false, stream:false,
    options:{num_ctx:8192, num_predict:8}, messages:[{role:"user", content:$p}]}' >"$TMP/req.json"
  local code n
  code="$(http POST /api/chat "$TMP/req.json")"
  if [ "$code" != 200 ]; then
    emit api-ctx FAIL "POST /api/chat -> HTTP $code"
    return 0
  fi
  n="$(jq -r '.prompt_eval_count // 0' "$TMP/body")"
  if [ "$n" -ge 6900 ]; then
    emit api-ctx PASS "prompt_eval_count=$n with num_ctx=8192 (native API applies num_ctx)"
  else
    emit api-ctx FAIL "prompt_eval_count=$n (< 6900): num_ctx not applied or prompt too short"
  fi
}

check_openai() { # informational: why tier 2 never uses /v1/*
  jq -n --arg m "$GEN_MODEL" --arg p "$(long_prompt)" '{model:$m, stream:false, max_tokens:8,
    messages:[{role:"user", content:$p}]}' >"$TMP/req.json"
  local code n
  code="$(http POST /v1/chat/completions "$TMP/req.json")"
  if [ "$code" != 200 ]; then
    emit api-openai WARN "/v1/chat/completions -> HTTP $code"
    return 0
  fi
  n="$(jq -r '.usage.prompt_tokens // 0' "$TMP/body")"
  emit api-openai PASS "usage.prompt_tokens=$n on /v1 (no num_ctx option there; tier 2 uses /api/* only, Y3.1)"
}

check_embed() {
  local code
  code="$(http GET /api/tags)"
  if [ "$code" = 200 ] && ! jq -e --arg m "$EMBED_MODEL" '.models[] | select(.name | startswith($m))' "$TMP/body" >/dev/null; then
    emit api-embed WARN "$EMBED_MODEL not pulled yet (T3.1b)"
    return 0
  fi
  jq -n --arg m "$EMBED_MODEL" '{model:$m, input:"Kündigung des Mietvertrags"}' >"$TMP/req.json"
  code="$(http POST /api/embed "$TMP/req.json")"
  if [ "$code" = 200 ]; then
    emit api-embed PASS "dimension $(jq -r '.embeddings[0] | length' "$TMP/body")"
  else
    emit api-embed WARN "POST /api/embed -> HTTP $code"
  fi
}

check_detached() { # round 11 Y5.4: a detached process must outlive its SSH connection
  local pid
  # shellcheck disable=SC2029  # the remote command is built on the client on purpose
  pid="$(ssh "${SSH_OPTS[@]}" "$ALIAS" "$START_REMOTE" 2>"$TMP/ssh1.log" </dev/null || true)"
  if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
    emit detached-survives-logout FAIL "could not start the detached sleep: $(head -c 150 "$TMP/ssh1.log")"
    return 0
  fi
  sleep 5
  # shellcheck disable=SC2029  # the pid is interpolated on the client on purpose
  if ssh "${SSH_OPTS[@]}" "$ALIAS" "$(live_remote "$pid")" >"$TMP/ssh2.out" 2>&1 </dev/null \
    && grep -q alive "$TMP/ssh2.out"; then
    emit detached-survives-logout PASS "setsid nohup sleep (pid $pid) alive 5 s after logout; killed again"
  else
    emit detached-survives-logout FAIL "pid $pid gone 5 s after the SSH connection closed"
  fi
}

main() {
  echo "# tunnel_check $(date -u +%FT%TZ) base=$BASE"
  if check_fwd; then
    check_tags
    check_chat
    check_ctx
    check_openai
    check_embed
  fi
  check_detached
}

main
