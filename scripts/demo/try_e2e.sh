#!/usr/bin/env bash
# scripts/demo/try_e2e.sh: the Try-it e2e of ui-spec §14.2 against the REAL demo stack (T8.4, Y7.5, N5.4, P5.4).
# Runs on the VM only (never a hosted runner, never a PR check). One demo instance, `rag-demo-e2e` of compose project
# `pruefstand-demo-e2e` (infra/deploy/demo/compose.yml, profile e2e; own qdrant/llm/embed, no default host port), and one
# long-lived Playwright container (pinned image, --network host, the checkout mounted) that installs, builds and runs
# the specs, so the service user needs only Docker. The whole run holds stack.lock (one stack session, A13-M8).
#
# Own project: never the production `pruefstand-demo` (E2E_PROJECT). Per group (rows that need the same env): restart rag-demo-e2e with the group's env and wait for /v1/health; per
# combination (row x project x theme x locale, from `playwright --list`): the in-container reset (POST
# /v1/_test/reset, expects 204, retries on 409 for up to 60 s), then ONE `docker exec` Playwright call with the exact
# title. try.spec.ts never calls the reset. Exit code = the first failing Playwright call's (all combinations run).
#
# usage: scripts/demo/try_e2e.sh            env: PORT_OFFSET (0; 10000 on an agent dev stack), E2E_PORT, STACK_LOCK,
#                                                STACK_LOCK_WAIT (s), PW_IMAGE, KEEP_STACK=1 (leave the stack up)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

stack_lock="${STACK_LOCK:-$HOME/pruefstand/stack.lock}"
if [ "${TRY_E2E_LOCKED:-0}" != "1" ]; then
  mkdir -p "$(dirname "$stack_lock")"
  TRY_E2E_LOCKED=1 exec flock -w "${STACK_LOCK_WAIT:-3600}" "$stack_lock" "${BASH_SOURCE[0]}" "$@"
fi

E2E_PORT="${E2E_PORT:-$((8091 + ${PORT_OFFSET:-0}))}"
SITE_PORT=4175
PW_IMAGE="${PW_IMAGE:-mcr.microsoft.com/playwright:v1.56.1-noble}"
pw="try-e2e-pw-$$"
export E2E_PORT DEMO_ALLOWED_ORIGIN="http://localhost:${SITE_PORT}"
# The e2e run has its OWN compose project (own containers, network and volumes), so its teardown (`down -v`) can never
# touch the production demo project `pruefstand-demo` (its qdrant_data index, llm, embed, rag-demo).
project="${E2E_PROJECT:-pruefstand-demo-e2e}"
if [ "$project" = "pruefstand-demo" ]; then
  printf 'try_e2e: E2E_PROJECT must not be the production project pruefstand-demo\n' >&2
  exit 2
fi
compose=(docker compose -p "$project" -f infra/deploy/demo/compose.yml --profile e2e)
pw_path="/tmp/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
config="playwright.try.config.ts"
reset_py='import urllib.request as u, urllib.error as e
try:
    print(u.urlopen(u.Request("http://localhost:8000/v1/_test/reset", method="POST")).status)
except e.HTTPError as x:
    print(x.code)'

started=$SECONDS
resets=0
first_rc=0
failed=()

log() { printf 'try_e2e: %s\n' "$*"; }
pwx() { docker exec -e "PATH=$pw_path" -e "E2E_PORT=$E2E_PORT" -e CI=1 "$pw" "$@"; }

cleanup() {
  local rc=$?
  docker exec "$pw" sh -c 'test -f /tmp/srv.pid && kill "$(cat /tmp/srv.pid)"' >/dev/null 2>&1 || true
  docker rm -f "$pw" >/dev/null 2>&1 || true
  if [ "${KEEP_STACK:-0}" != "1" ]; then
    "${compose[@]}" down --remove-orphans -v >/dev/null 2>&1 || true
  fi
  return "$rc"
}
trap cleanup EXIT

serve() { # <set dir under .sets>
  pwx sh -c "test -f /tmp/srv.pid && kill \$(cat /tmp/srv.pid); true" >/dev/null 2>&1 || true
  sleep 1
  docker exec -d -e "PATH=$pw_path" "$pw" sh -c "echo \$\$ > /tmp/srv.pid; exec node e2e/static-server.mjs .sets/$1 $SITE_PORT"
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:${SITE_PORT}/de/try/" && return 0
    sleep 1
  done
  log "site $1 did not come up on ${SITE_PORT}"
  return 1
}

restart_instance() { # <ENV=VALUE>...
  env "$@" "${compose[@]}" up -d --force-recreate --no-deps --wait rag-demo-e2e >/dev/null
  curl -fsS "http://127.0.0.1:${E2E_PORT}/v1/health" >/dev/null
}

reset_instance() { # <title>: 204 or fail naming the test (409 = a generation still runs: retry every 2 s, <= 60 s)
  local code
  for _ in $(seq 1 30); do
    code="$("${compose[@]}" exec -T rag-demo-e2e python -c "$reset_py" | tr -d '\r\n')"
    if [ "$code" = "204" ]; then
      resets=$((resets + 1))
      return 0
    fi
    [ "$code" = "409" ] || break
    sleep 2
  done
  log "reset before '$1' answered '${code:-nothing}', expected 204"
  return 1
}

list_titles() { # prints "<project>\t<title>" for every combination
  pwx pnpm exec playwright test -c "$config" --list --reporter=json 2>/dev/null |
    jq -r '.. | objects | select(has("specs")) | .specs[] | .title as $t | .tests[] | "\(.projectName)\t\($t)"'
}

run_group() { # <name> <rows, "|"-separated> <reset yes|no>
  local name="$1" rows="$2" do_reset="$3"
  log "group $name: rows [$rows]"
  local proj title row rc n=0
  while IFS=$'\t' read -r -u 3 proj title; do
    row="${title% * *}"
    case "|$rows|" in *"|$row|"*) ;; *) continue ;; esac
    if [ "$do_reset" = "yes" ] && ! reset_instance "$title"; then
      failed+=("$proj $title (reset)")
      [ "$first_rc" != 0 ] || first_rc=1
      continue
    fi
    n=$((n + 1))
    rc=0
    pwx pnpm exec playwright test -c "$config" --project "$proj" -g "${title}\$" >"/tmp/try-e2e-$$.out" 2>&1 || rc=$?
    if [ "$rc" != 0 ]; then
      tail -40 "/tmp/try-e2e-$$.out"
      failed+=("$proj $title")
      [ "$first_rc" != 0 ] || first_rc="$rc"
    fi
  done 3<<<"$titles" # fd 3: docker/compose calls in the loop must not eat the list from stdin
  log "group $name: $n combinations run"
}

# --- preflight ---------------------------------------------------------------------------------------------
command -v jq >/dev/null || { log "jq is required"; exit 2; }
model="${LIVE_MODEL_DIR:-$HOME/.cache/pruefstand/models}/${LIVE_LLM_GGUF:-qwen2.5-0.5b-instruct-q4_k_m.gguf}"
[ -f "$model" ] || { log "model file missing: $model (scripts/models/fetch.py)"; exit 2; }
docker image inspect "$PW_IMAGE" >/dev/null 2>&1 || docker pull "$PW_IMAGE" >/dev/null

# --- toolchain, builds ---------------------------------------------------------------------------------------
log "Playwright container, E2E_PORT=$E2E_PORT"
docker run -d --name "$pw" --network host --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e COREPACK_HOME=/tmp/corepack \
  -v "$root":/work -w /work/apps/dashboard "$PW_IMAGE" sleep infinity >/dev/null
pwx sh -c 'mkdir -p /tmp/bin /tmp/home && corepack enable --install-directory /tmp/bin && pnpm install --frozen-lockfile' >/dev/null
api="http://127.0.0.1:${E2E_PORT}"
log "builds populated-try and populated-try-timeout"
docker exec -w /work -e "PATH=$pw_path" -e "NEXT_PUBLIC_DEMO_API_URL=$api" "$pw" \
  scripts/dashboard/build_set.sh populated --out populated-try >/dev/null
docker exec -w /work -e "PATH=$pw_path" -e "NEXT_PUBLIC_DEMO_API_URL=$api" -e NEXT_PUBLIC_DEMO_TIMEOUT_S=1 "$pw" \
  scripts/dashboard/build_set.sh populated --out populated-try-timeout >/dev/null
titles="$(list_titles)"
[ -n "$titles" ] || { log "playwright --list found no Try-it tests"; exit 1; }
rows_total="$(cut -f2 <<<"$titles" | sed 's/ [a-z]* [a-z]*$//' | sort -u | wc -l)"
combos_total="$(wc -l <<<"$titles")"

# --- stack ---------------------------------------------------------------------------------------------------
log "stack up (qdrant, llm, embed, index, rag-demo-e2e)"
"${compose[@]}" up -d --build --wait rag-demo-e2e >/dev/null
curl -fsS "$api/v1/health" >/dev/null

# --- groups ---------------------------------------------------------------------------------------------------
# TRY_E2E_GROUPS=busy,budget runs only those groups (debugging); the default runs all of them.
want() { [ -z "${TRY_E2E_GROUPS:-}" ] || case ",$TRY_E2E_GROUPS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
group() { # <name> <rows> <env VAR=VALUE>: restart with the env (none: keep the defaults), then run the rows
  want "$1" || return 0
  if [ "${3:-}" ]; then restart_instance "$3"; fi
  run_group "$1" "$2" yes
}

serve populated-try
group defaults "T-IDLE|T-INVALID|T-LOADING T-SLOW|T-CANCELLED|T-SUCCESS|T-REFUSED"
group rate-limit "T-RATE-LIMITED" DEMO_RATE_PER_MIN=1
group busy "T-BUSY" DEMO_MAX_CONCURRENCY=1
group daily-limit "T-DAILY-LIMIT" DEMO_DAILY_PER_KEY=1
# DEMO_DAILY_REQUESTS=0 would trip the per-day request limiter (daily_limit) before the budget; one token cannot
# cover the worst case of any generation, so the budget refuses first: budget_exhausted (503).
group budget "T-BUDGET" DEMO_DAILY_TOKENS=1
group demo-off "T-DEMO-OFF" DEMO_ENABLED=false
if want stopped; then
  "${compose[@]}" stop rag-demo-e2e >/dev/null
  run_group stopped "T-NETWORK" no
fi
# T-TIMEOUT runs last, on the build with a 1 s client timeout; the page holds its request (e2e/delay.ts), so the
# stopped instance is never reached and no reset is needed.
if want timeout; then
  serve populated-try-timeout
  run_group timeout "T-TIMEOUT" no
fi

# --- summary ---------------------------------------------------------------------------------------------------
log "rows: $rows_total, combinations listed: $combos_total, resets (204): $resets, wall time: $((SECONDS - started)) s"
if [ "${#failed[@]}" -gt 0 ]; then
  log "FAILED (${#failed[@]}):"
  printf '  %s\n' "${failed[@]}"
  exit "$first_rc"
fi
log "all combinations passed"
