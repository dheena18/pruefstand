#!/usr/bin/env bash
# Re-record tests/cassettes/llm from REAL calls to the pinned llama.cpp test model (T1.4 S10).
#   make cassettes
# Fetches the model, starts compose service `llm` under the stack lock (make stack-run; the stack is
# torn down on exit), records server_503.yaml while the server is still loading the model, then runs
# the recording tests (`--record-mode=rewrite`) and writes the backend-level JSON cassettes.
# Nothing is ever edited by hand; a recording that does not show the intended behaviour fails the run.
# T1.13 adds a second stage (`--rag-demo`): the full `live` stack (llm, TEI, Qdrant, rag-demo) records the
# generator and TEI cassettes of apps/rag-demo/tests/cassettes and the contract examples (`make cassettes-contract`).
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

rag_demo_inner() {
  # T1.13 S8: runs inside `make stack-run PROFILES="core live dev"` (all ports are exported by mk/docker.mk).
  local rag_cassettes=apps/rag-demo/tests/cassettes
  make --no-print-directory index-slice
  rm -f "$rag_cassettes"/*.yaml
  RAG_RECORD=1 RECORD_LLM_URL="http://127.0.0.1:${LLM_HOST_PORT:-8080}" \
    RECORD_EMBED_URL="http://127.0.0.1:${EMBED_HOST_PORT:-8090}" \
    uv run pytest apps/rag-demo/tests/live/test_record.py --record-mode=rewrite -q -p no:cacheprovider
  local day
  day="$(date +%F)"
  for f in "$rag_cassettes"/*.yaml; do
    { echo "# recorded: $day, git: $(git rev-parse --short HEAD), by scripts/models/record_cassettes.sh"; cat "$f"; } > "$f.tmp"
    mv "$f.tmp" "$f"
  done
  make --no-print-directory rag-demo-bug BUG=tenant_filter_post_topk
  # the bug instance needs a moment to become healthy
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${BUG_PORT:-$((8001 + ${PORT_OFFSET:-0}))}/v1/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  make --no-print-directory cassettes-contract
  uv run pytest apps/rag-demo/tests/unit -q -p no:cacheprovider
}

dataset_stage() {
  # T4.2 S7: records the REAL GitHub Models datagen calls used by the dataset cassette tests. Skipped
  # unless PRUEFSTAND_GH_MODELS_TOKEN (Models: read, D333) is set; models.github.ai must be reachable
  # (not from the VM, D604: run it on the owner's laptop or in an Actions job with models: read).
  if [ -z "${PRUEFSTAND_GH_MODELS_TOKEN:-}" ]; then
    echo "record_cassettes: dataset stage skipped (PRUEFSTAND_GH_MODELS_TOKEN is not set)" >&2
    return 0
  fi
  local dir=packages/pruefstand/tests/cassettes/dataset
  rm -f "$dir"/*.json "$dir"/support/*.json
  # T4.3: the support-check test records into $dir/support (PRUEFSTAND_RECORD_SUPPORT=1)
  PRUEFSTAND_RECORD_DATASET=1 PRUEFSTAND_RECORD_SUPPORT=1 \
    uv run pytest packages/pruefstand/tests/live/dataset -m live -q -p no:cacheprovider
  uv run pytest packages/pruefstand/tests/unit/dataset/test_generate_cassette.py \
    packages/pruefstand/tests/unit/dataset/test_filters_cassette.py -q -p no:cacheprovider
  git --no-pager diff --stat -- "$dir" || true
}

perturb_stage() {
  # T4.5 S1; also `--perturb` (cassettes-models.yml, D900: judge = a github/<model>, there is no A40 in Actions).
  if [ -n "${PRUEFSTAND_GH_MODELS_TOKEN:-}" ] && [ -n "${PRUEFSTAND_PERTURB_REWRITE_MODEL:-}" ] \
    && [ -n "${PRUEFSTAND_PERTURB_JUDGE_MODEL:-}" ]; then
    rm -rf packages/pruefstand/tests/cassettes/perturb
    uv run pytest packages/pruefstand/tests/live/perturb/test_record_perturb.py --record-mode=rewrite -q -p no:cacheprovider
    uv run pytest packages/pruefstand/tests/unit/perturb/test_cassettes.py -q -p no:cacheprovider
    git --no-pager diff --stat -- packages/pruefstand/tests/cassettes/perturb || true
  else
    echo "record_cassettes: perturb stage skipped (needs PRUEFSTAND_GH_MODELS_TOKEN and PRUEFSTAND_PERTURB_{REWRITE,JUDGE}_MODEL)" >&2
  fi
}

if [ "${1:-}" = "--dataset" ]; then
  dataset_stage
  exit $?
fi
if [ "${1:-}" = "--perturb" ]; then
  perturb_stage
  exit $?
fi
if [ "${1:-}" = "--judges" ]; then
  # T5.2a: real answers of the A40 judge for packages/pruefstand/tests/unit/judges/test_judge_cassette.py.
  # Run on the VM under the GPU lock with the judge loaded: pruefstand-lock bash scripts/models/record_cassettes.sh --judges
  rm -f packages/pruefstand/tests/cassettes/judges/*.json
  PRUEFSTAND_RECORD_JUDGES=1 uv run pytest packages/pruefstand/tests/live/judges/test_record_judges.py -m "live and gpu" -q -p no:cacheprovider
  uv run pytest packages/pruefstand/tests/unit/judges/test_judge_cassette.py -q -p no:cacheprovider
  exit $?
fi
if [ "${1:-}" = "--review" ]; then
  # T4.7a: real answers of the A40 judge (gemma3:12b) for packages/pruefstand/tests/unit/dataset/test_model_review_cassette.py.
  # Run on the VM under the GPU lock with the judge loaded: pruefstand-lock bash scripts/models/record_cassettes.sh --review
  rm -f packages/pruefstand/tests/cassettes/dataset_review/*.json
  PRUEFSTAND_RECORD_REVIEW=1 uv run pytest packages/pruefstand/tests/live/dataset/test_record_review.py -m "live and gpu" -q -p no:cacheprovider
  PRUEFSTAND_RECORD_REVIEW=1 uv run pytest packages/pruefstand/tests/live/dataset/test_record_embeddings.py -m "live and gpu" -q -p no:cacheprovider
  uv run pytest packages/pruefstand/tests/unit/dataset/test_model_review_cassette.py -q -p no:cacheprovider
  exit $?
fi
if [ "${1:-}" = "--inner" ]; then
  inner
  exit $?
fi
if [ "${1:-}" = "--rag-demo-inner" ]; then
  rag_demo_inner
  exit $?
fi

uv run python scripts/models/fetch.py
export LIVE_LLM_GGUF="$MODEL_FILE"
make --no-print-directory stack-run PROFILES="core live dev" SERVICES=llm \
  CMD="bash scripts/models/record_cassettes.sh --inner"
git --no-pager diff --stat -- "$CASSETTES" || true

# T1.13: second stage, the whole live stack for the rag-demo cassettes and the contract examples.
uv run python scripts/models/fetch.py --manifest infra/models/live-models.yaml
unset LIVE_LLM_GGUF  # the compose default is the pinned live generator
make --no-print-directory stack-run PROFILES="core live dev" \
  CMD="bash scripts/models/record_cassettes.sh --rag-demo-inner"
git --no-pager diff --stat -- apps/rag-demo/tests/cassettes packages/pruefstand/tests/contract/examples || true

# T1.10: third stage, the CLI target cassettes (good rag-demo + two bug instances; make cassettes-target).
make --no-print-directory cassettes-target
git --no-pager diff --stat -- packages/pruefstand/tests/cassettes/target || true

# T4.2: fourth stage, the datagen cassettes (real GitHub Models calls; skipped without the token).
dataset_stage

# T4.5: fifth stage, the LLM-assisted perturbations (compound_split, register, gender, colloquial).
# Rewrites come from the pinned GitHub Models datagen model, equivalence checks from the A40 judge in day
# mode, so this stage needs PRUEFSTAND_GH_MODELS_TOKEN, PRUEFSTAND_PERTURB_REWRITE_MODEL (github/<model>),
# PRUEFSTAND_PERTURB_JUDGE_MODEL (ollama/<tag>) and the tunnel; run it as `pruefstand-lock make cassettes`
# on the VM. Without them the stage is skipped (the unit replay test then skips as well).
perturb_stage
