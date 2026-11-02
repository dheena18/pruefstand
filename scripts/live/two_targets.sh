#!/usr/bin/env bash
# Two rag-demo instances from compose profile `live` for the CLI evidence runs (T1.10 S9):
#   good  on the rag-demo port of the stack (8000 + PORT_OFFSET)   apps/rag-demo/configs/rag.yaml
#   bug   on the next port   (8001 + PORT_OFFSET)                  apps/rag-demo/configs/bugs/<bug>.yaml
# usage: scripts/live/two_targets.sh <bug>      e.g. tenant_filter_post_topk or no_citations
# Needs the running live stack and the slice index:
#   make up PROFILES="core live dev" WAIT=1 && make index-slice
# Prints the two base URLs; `make down` removes both instances with the rest of the stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
BUG="${1:-}"
if ! [[ "$BUG" =~ ^[a-z0-9_]+$ ]] || [ ! -f "apps/rag-demo/configs/bugs/$BUG.yaml" ]; then
  echo "usage: $0 <bug>   (one of: $(cd apps/rag-demo/configs/bugs && ls | sed 's/\.yaml$//' | tr '\n' ' '))" >&2
  exit 2
fi

GOOD_PORT="$(make --no-print-directory ports | awk '$1 == "rag-demo" {print $2}')"
BUG_PORT=$((GOOD_PORT + 1))
export BUG_PORT

wait_healthy() {
  local url="$1"
  for _ in $(seq 1 120); do
    if curl -fsS "$url/v1/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "two_targets: $url never became healthy" >&2
  return 1
}

docker rm -f "rag-demo-bug-$BUG" >/dev/null 2>&1 || true
make --no-print-directory rag-demo-bug BUG="$BUG" BUG_PORT="$BUG_PORT" >/dev/null
wait_healthy "http://127.0.0.1:$GOOD_PORT"
wait_healthy "http://127.0.0.1:$BUG_PORT"
echo "good=http://127.0.0.1:$GOOD_PORT bug=http://127.0.0.1:$BUG_PORT ($BUG)"
