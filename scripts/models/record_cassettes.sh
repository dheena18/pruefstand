#!/usr/bin/env bash
# Re-record tests/cassettes/llm from REAL calls to the pinned llama.cpp test model (T1.4 S10).
#   make cassettes
# Fetches the model, starts compose service `llm` under the stack lock (make stack-run; the stack is
# torn down on exit), records server_503.yaml while the server is still loading the model, then runs
# the recording tests (`--record-mode=rewrite`) and writes the backend-level JSON cassettes.
# Nothing is ever edited by hand; a recording that does not show the intended behaviour fails the run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
CASSETTES=packages/pruefstand/tests/cassettes/llm
LIVE_TESTS=packages/pruefstand/tests/live/llm
MODEL_FILE=qwen2.5-0.5b-instruct-q4_k_m.gguf
MODEL_SHA=74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
MODEL_ID=openai_compatible_local/qwen2.5-0.5b-instruct

record_503() {
  # The 503 only exists while llama.cpp loads the model: the test starts the service itself and calls
  # the moment /health answers 503.
  for attempt in 1 2 3 4 5 6; do
    make --no-print-directory down >/dev/null
    if PRUEFSTAND_RECORD_START_CMD="make --no-print-directory up SERVICES=llm" uv run pytest "$LIVE_TESTS/test_record.py" -k server_503 --record-mode=rewrite -q -p no:cacheprovider; then
      return 0
    fi
    echo "record_cassettes: attempt $attempt missed the loading window, retrying" >&2
  done
  echo "record_cassettes: could not record a 503 answer" >&2
  return 1
}

wait_healthy() {
  local url="http://localhost:${LLM_HOST_PORT:-8080}/health"
  for _ in $(seq 1 120); do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "record_cassettes: llm service never became healthy" >&2
  return 1
}

add_header() {
  # Header comment: recorded date, model id, GGUF sha256 (prepended by this script, never by hand).
  local day
  day="$(date +%F)"
  for f in "$CASSETTES"/*.yaml; do
    grep -v '^# recorded:' "$f" > "$f.tmp"
    { echo "# recorded: $day, model: $MODEL_ID, sha256: $MODEL_SHA"; cat "$f.tmp"; } > "$f"
    rm -f "$f.tmp"
  done
}

inner() {
  export PRUEFSTAND_TEST_LLM_URL="http://localhost:${LLM_HOST_PORT:-8080}/v1"
  rm -f "$CASSETTES"/*.yaml "$CASSETTES"/backend/*.json
  record_503
  grep -q 'code: 503' "$CASSETTES/server_503.yaml" || { echo "server_503.yaml holds no 503" >&2; return 1; }
  wait_healthy
  uv run pytest "$LIVE_TESTS/test_record.py" -k "not server_503" --record-mode=rewrite -q -p no:cacheprovider
  add_header
  uv run pytest packages/pruefstand/tests/unit/llm -q -p no:cacheprovider
}

if [ "${1:-}" = "--inner" ]; then
  inner
  exit $?
fi

uv run python scripts/models/fetch.py
export LIVE_LLM_GGUF="$MODEL_FILE"
make --no-print-directory stack-run PROFILES="core live dev" SERVICES=llm \
  CMD="bash scripts/models/record_cassettes.sh --inner"
git --no-pager diff --stat -- "$CASSETTES" || true
