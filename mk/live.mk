# Targets of the tier-1 `live` stack (T1.13). Included by the root Makefile (-include mk/*.mk, after docker.mk).
.PHONY: index-slice rag-demo-bug cassettes-contract

# Builds the Qdrant collection from corpus/slice_v1/ with the real TEI container and writes the snapshot that
# T1.12 caches. Needs a running `live` stack: make up PROFILES="core live dev" WAIT=1  (ports come from docker.mk).
index-slice:
	QDRANT_URL=http://127.0.0.1:$(QDRANT_HTTP_PORT) EMBED_URL=http://127.0.0.1:$(EMBED_HOST_PORT) \
	    uv run python scripts/slice/index_slice.py

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
