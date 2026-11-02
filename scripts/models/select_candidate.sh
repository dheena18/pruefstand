#!/usr/bin/env bash
# Measure one generator candidate end to end (T1.13 S7): start the `live` stack with its GGUF, index the slice,
# start the injection_guard_off instance, run scripts/models/smoke_select.py, tear everything down.
#   bash scripts/models/select_candidate.sh <gguf file in ~/.cache/pruefstand/models> <label>
# The rag-demo config must name the candidate (generator.model / family) so the Qwen3 switch is exercised.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "--inner" ]; then
  label="$2"
  make --no-print-directory index-slice
  make --no-print-directory rag-demo-bug BUG=injection_guard_off
  bug_port="${BUG_PORT:-$((8001 + ${PORT_OFFSET:-0}))}"
  for _ in $(seq 1 90); do
    curl -fsS "http://127.0.0.1:${bug_port}/v1/health" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "http://127.0.0.1:${bug_port}/v1/health" >/dev/null || {
    echo "select_candidate: the injection_guard_off instance is not healthy" >&2
    docker logs "rag-demo-bug-injection_guard_off" 2>&1 | tail -20 >&2 || true
    exit 1
  }
  uv run python scripts/models/smoke_select.py --candidate "$label" \
    --url "http://127.0.0.1:${RAG_DEMO_HOST_PORT:-8000}" --guard-off-url "http://127.0.0.1:${bug_port}"
  exit 0
fi

export LIVE_LLM_GGUF="$1"
make --no-print-directory stack-run PROFILES="core live dev" \
  CMD="bash scripts/models/select_candidate.sh --inner $2"
