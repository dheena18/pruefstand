# Targets of the tier-1 `live` stack (T1.13). Included by the root Makefile (-include mk/*.mk, after docker.mk).
.PHONY: index-slice rag-demo-bug cassettes-contract cassettes-target

# Builds the Qdrant collection slice_v2 (+ alias chunks_active) from corpus/slice_v1/ with `rag-demo index` and the real TEI
# container, then writes the snapshot that T1.12 caches (snapshots carry no alias: a restore re-creates it). Needs a running `live` stack: make up PROFILES="core live dev" WAIT=1  (ports come from docker.mk).
index-slice:
	QDRANT_URL=http://127.0.0.1:$(QDRANT_HTTP_PORT) EMBED_URL=http://127.0.0.1:$(EMBED_HOST_PORT) \
	    uv run rag-demo index --corpus corpus/slice_v1 --encoder tei --collection slice_v2
	QDRANT_URL=http://127.0.0.1:$(QDRANT_HTTP_PORT) uv run python scripts/slice/index_slice.py

# A second rag-demo instance with a bug config (apps/rag-demo/configs/bugs/<BUG>.yaml) on BUG_PORT (default 8001
# + PORT_OFFSET; Y1.4). `make down` removes it with the rest of the stack.
BUG ?= tenant_filter_post_topk
BUG_PORT ?= $(shell echo $$(( 8001 + $(PORT_OFFSET) )))
export BUG_PORT
rag-demo-bug:
	$(COMPOSE) run -d --no-deps --name rag-demo-bug-$(BUG) -p 127.0.0.1:$(BUG_PORT):8000 \
	    -e RAG_CONFIG=/app/configs/bugs/$(BUG).yaml rag-demo

# Replaces the T1.3/T1.8 contract examples by recordings of the real app (needs the running stack, see above).
cassettes-contract:
	RAG_DEMO_URL=http://127.0.0.1:$(RAG_DEMO_HOST_PORT) \
	    uv run python scripts/models/record_contract.py --bug-url http://127.0.0.1:$(BUG_PORT)

# T1.10: records the exchanges of the good rag-demo and of two bug instances (tenant_filter_post_topk,
# no_citations) for the CLI unit tests: packages/pruefstand/tests/cassettes/target/{good,bug_tenant,bug_citations}.
# One stack session under stack.lock; needs the pinned models (scripts/models/fetch.py --manifest ...).
cassettes-target:
	$(MAKE) --no-print-directory stack-run PROFILES="core live dev" CMD="bash scripts/live/record_targets.sh"
