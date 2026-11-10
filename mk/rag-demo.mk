# Targets of the reference RAG app's indexer (T3.4). Included by the root Makefile (-include mk/*.mk).
.PHONY: index fetch-tokenizer fetch-generator-tokenizer

# Tier 1 (tei): needs the `live` stack (make up PROFILES="core live dev" WAIT=1).
# Tier 2 (ollama): needs the day-mode models (make gpu-up) and the tunnel; run it as `pruefstand-lock make index ...`
# only when the lock is needed (an embedding pass holds GPU0); Qdrant is the dev one (port from docker.mk).
# PR-scoped build: make index INDEX_ARGS="--collection pr_7_abc1234 --no-alias"; drop: INDEX_ARGS="--drop pr_7_abc1234" CORPUS=
CORPUS ?= corpus/slice_v1
ENCODER ?= tei
INDEX_ARGS ?=
EMBED_TOKENIZER ?= $(HOME)/.cache/pruefstand/models/tokenizers/bge-m3.json

# Downloads the pinned bge-m3 tokenizer.json (sha256 from infra/gpu/models.yaml) for the truncated_chunks count.
fetch-tokenizer:
	RAG_MODEL_CATALOGUE=infra/gpu/models.yaml uv run python -m rag_demo.index.fetch_tokenizer --out $(EMBED_TOKENIZER)

index:
	QDRANT_URL=http://127.0.0.1:$(QDRANT_HTTP_PORT) EMBED_URL=http://127.0.0.1:$(EMBED_HOST_PORT) \
	    OLLAMA_GPU0_URL=$${OLLAMA_GPU0_URL:-http://127.0.0.1:11434} RAG_EMBED_TOKENIZER=$(EMBED_TOKENIZER) \
	    uv run rag-demo index $(if $(CORPUS),--corpus $(CORPUS) --encoder $(ENCODER)) $(INDEX_ARGS)

GENERATOR_TOKENIZER ?= $(HOME)/.cache/pruefstand/models/tokenizers/generator.json

# Downloads the pinned generator tokenizer.json (the catalogue id comes from rag.gpu.yaml) for the prompt budget (T3.6).
fetch-generator-tokenizer:
	RAG_MODEL_CATALOGUE=infra/gpu/models.yaml uv run python -m rag_demo.index.fetch_tokenizer \
	    --config apps/rag-demo/configs/rag.gpu.yaml --out $(GENERATOR_TOKENIZER)

# T3.7: the canary registry the gpu isolation suite (apps/rag-demo/tests/gpu/test_quality_and_isolation.py) reads, a
# variable of the existing test-gpu target only. Default: the public registry of the indexed slice; set CANARY_REGISTRY
# to datasets/canaries/<corpus_version>/canaries.json once the T2.6 corpus is the indexed one.
test-gpu: export CANARY_REGISTRY ?= $(CURDIR)/corpus/slice_v1/canaries.public.json
