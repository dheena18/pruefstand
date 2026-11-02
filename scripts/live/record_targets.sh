#!/usr/bin/env bash
# Records tests/cassettes/target/{good,bug_tenant,bug_citations} from the REAL rag-demo (T1.10 S9).
# Runs inside `make stack-run PROFILES="core live dev"` (see `make cassettes-target`): indexes the slice,
# then asks every case of datasets/fixtures/mini_v0 once per target. Nothing is edited by hand.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
OUT=packages/pruefstand/tests/cassettes/target
CASES=datasets/fixtures/mini_v0/smoke.jsonl

make --no-print-directory index-slice
GOOD_PORT="$(make --no-print-directory ports | awk '$1 == "rag-demo" {print $2}')"
uv run python scripts/live/record_target.py --url "http://127.0.0.1:$GOOD_PORT" --cases "$CASES" --out "$OUT/good"

record_bug() {
  local bug="$1" name="$2"
  bash scripts/live/two_targets.sh "$bug"
  uv run python scripts/live/record_target.py --url "http://127.0.0.1:$((GOOD_PORT + 1))" --cases "$CASES" --out "$OUT/$name"
  docker rm -f "rag-demo-bug-$bug" >/dev/null
}
record_bug tenant_filter_post_topk bug_tenant
record_bug no_citations bug_citations
