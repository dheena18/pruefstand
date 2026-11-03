# rag-demo: the reference RAG app (system under test)

A small, real, CPU-only German RAG app that serves **Target HTTP API v1** (`/v1/query`, `/v1/retrieve`, `/v1/info`,
`/v1/health`; `schemas/target-api-v1.openapi.yaml`) over the committed 5-law slice corpus
(`corpus/slice_v1`, built by `scripts/slice/build_slice.py`). It never imports `pruefstand` and nothing
here reads `datasets/` (import-linter contract `sut-independent`). Tier-1 CI and every e2e test run
against it; T3.x extends the same app to the A40 stack.

| Part | Module | What it is |
| --- | --- | --- |
| Config | `config.py`, `models.py` | `RagConfig` (frozen, `extra=forbid`), `config_hash` (config + prompt bytes), `Settings` from the environment |
| Analysis | `analysis/` (`normalise`, `abbreviations`, `compound`, `analyzer`, `sparse`) | `GermanAnalyzer` and `SparseEncoder`, see "Analyzer" below |
| Dense | `index/encoders.py` | `TeiDenseEncoder` (TEI CPU, e5 `query: ` / `passage: ` prefixes, `truncate: true`) and `OllamaDenseEncoder` (native `/api/embed`, catalogue options, unit vectors) |
| Index | `index/` (`corpus_reader`, `indexer`, `naming`, `qdrant_admin`, `tokens`), `cli.py` | `rag-demo index`: corpus lines validated by `index/chunk.schema.json`; one Qdrant collection per index fingerprint, `tenant_id` tenant index, atomic `chunks_active` alias |
| Retrieval | `retrieval/` (`filters`, `query_builder`, `retriever`, `rerank`, `store`, `corpus_meta`, `bugs`, `testing`) | `QdrantRetriever`: one Query API call, dense + sparse prefetch, tenant filter inside **every** prefetch and on the fused query, RRF `k` 60, optional `rerank-cpu` reranker, post-condition guard; backs `/v1/query` and `/v1/retrieve`; see "Retrieval" below |
| Generation | `generate.py`, `prompts/*.txt` | OpenAI-compatible (llama.cpp) client `OpenAICompatGenerator`, prompt building, injection guard, output guard, `<think>` strip |
| API | `api.py`, `schemas.py`, `info.py`, `wiring.py` | `create_app`, response mapping, `/v1/info` (`info.py`), the collaborators per profile (`wiring.py`), `/v1/health` |
| Tier 2 | `catalogue.py`, `endpoints.py`, `generate_ollama.py` | catalogue validation (D453), endpoint rules (D454), `OllamaChatGenerator` on native `/api/chat` |

## Bug switches (all in `configs/rag.yaml`; default = correct behaviour)

`configs/bugs/<name>.yaml` is a full copy of `rag.yaml` that differs in exactly one line (a unit test checks it).

| Switch | Correct | Bug config | What the bug does |
| --- | --- | --- | --- |
| `tenant_filter` | `inside` | `tenant_filter_post_topk` | no filter in the Qdrant prefetches; filtered in Python **after** the top-k cut, then backfilled from the unfiltered list (M8) |
| `shared_public_merge` | `filtered` | `shared_public_unfiltered` | a second query for `shared_public` without any tenant filter is merged in (M9) |
| `prompt_file` | `prompts/answer_de_v1.txt` | `no_citations`, `no_refusal` | prompt without the citation / refusal instruction (M5, M6) |
| `answer_language` | `auto` | `answer_language_en` | the system prompt forces English (M12) |
| `injection_guard` | `on` | `injection_guard_off` | raw chunks in the prompt instead of `<dokument>` blocks without instruction lines (M7) |
| `system_prompt_guard` | `on` | `system_prompt_guard_off` | no 8-gram output filter against prompt leaks |
| `top_k` | `4` (tier 1) | `top_k_1` | one chunk (M10; statistical, tested in tier 2) |
| `reranker` | `off` (tier 1) / `on` (`rag.gpu.yaml`) | `reranker_off` (tier 2 only, `configs/bugs/gpu/`) | no `rerank-cpu` call, fused order (M1) |

`generator.enable_thinking: false` is part of the config hash; for Qwen3 families the request carries
`chat_template_kwargs.enable_thinking=false` and a leading `<think>` block is stripped and counted.
`PRUEFSTAND_CANDIDATE_API_KEY` (name set by `api_key_env`) is sent as a bearer token to the generator and
embedding service when set and non-empty (D216); it is never logged.

## Run it

```bash
uv run python scripts/models/fetch.py --manifest infra/models/live-models.yaml   # generator GGUF
make up PROFILES="core live dev" WAIT=1        # Qdrant, llama.cpp, TEI, rag-demo (VM: PORT_OFFSET=10000 from .env)
make index-slice                               # rag-demo index of corpus/slice_v1 into a fresh collection (alias chunks_active), writes .cache/pruefstand/qdrant/slice_v2.snapshot
make rag-demo-bug BUG=tenant_filter_post_topk  # second instance with a bug config on the next free port
curl -s -X POST 127.0.0.1:$(make -s ports | awk '/^rag-demo /{print $2}')/v1/query \
  -H 'content-type: application/json' \
  -d '{"tenant_id":"kanzlei_mueller","question":"Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?","request_id":"x"}'
```

Environment (`config.Settings`): `RAG_CONFIG` (path of the YAML inside the container, default
`/app/configs/rag.yaml`), `QDRANT_URL`, `LLM_URL`, `EMBED_URL`, `RAG_COLLECTION`, `GIT_SHA`, `IMAGE_DIGEST`,
`LLAMA_CPP_VERSION`, `MODEL_SHA256`, `RAG_MODEL_CATALOGUE`, `SERVING_ENGINE_VERSION`, `SERVING_GPU`. None of them is part of `config_hash`.

## Profiles: live (tier 1) and gpu (tier 2)

The same app runs two profiles, chosen by `RAG_CONFIG` (`profile:` in the file).

| | `configs/rag.yaml` (`live`) | `configs/rag.gpu.yaml` (`gpu`) |
| --- | --- | --- |
| Generator | `qwen2.5-0.5b` on llama.cpp (CPU), OpenAI-compatible `/v1` | `ollama/qwen3.8:27b-q8_0` on the A40s, native `/api/chat`, `think: false` |
| Embeddings | TEI CPU, e5-small | `ollama/bge-m3` via `/api/embed` (`OllamaDenseEncoder`, T3.4) |
| Models | pinned in `infra/models/live-models.yaml` | resolved from `infra/gpu/models.yaml` (`RAG_MODEL_CATALOGUE`), checked at config load |
| URLs | `LLM_URL`, `EMBED_URL` | env named by `endpoint_env` (`OLLAMA_GPU0_URL` on the dev stack, `LLM_PROXY_URL` in gate runs), checked at app start |
| Bug configs | `configs/bugs/*.yaml` | `configs/bugs/gpu/*.yaml` (the same eight switches on top of `rag.gpu.yaml`) |

`/v1/info.serving` is static: tier 2 reports the catalogue engine, quantisation and manifest digest plus
`SERVING_ENGINE_VERSION` and `SERVING_GPU` from the environment. Dev stack on the VM (no GPU device in the
container, host network, `127.0.0.1:18000`):

```bash
make up COMPOSE_FILES="infra/gpu/compose.gpu.yml infra/gpu/compose.rag-demo.yml" PROFILES="gpu dev" SERVICES=rag-demo-dev
curl -s 127.0.0.1:18000/v1/info
```

## Retrieval (T3.5)

`QdrantRetriever.retrieve(tenant_id, query, top_k)`: embed the query (dense) and tokenise it with the same analyzer as the index
(sparse); one `POST /collections/chunks_active/points/query` whose two prefetch legs (`retrieval.prefetch_k` 50 each) and
whose fused query all carry `tenant_id in {tenant, shared_public}` (`filters.tenant_filter`, the only place the filter is
built; `testing.assert_tenant_scoped` checks a request or a recorded body), RRF with `retrieval.rrf_k` 60; with
`reranker: on` the first `rerank.top_n` (10) hits are scored by `rerank-cpu` (`RERANK_URL`, no auth; passages cut to the
catalogue's 256 tokens, one batched request), then the list is cut to `top_k`. Before every query the collection metadata
must be `complete` with the app's analyzer fingerprint (else 503 "re-index", never a dense-only answer); a hit of a
foreign tenant raises `TenantIsolationError` (skipped only while a leak bug switch is on). `QDRANT_API_KEY` is sent as
`api-key`. `retrieval.hybrid: false` = dense only. `POST /v1/retrieve` returns the same chunks as `/v1/query` (`{"chunks": [...]}`,
no answer, no generator call); `rerank.on_retrieve: false` makes it skip the reranker (D222 fallback, part of `config_hash`).

## Indexing (T3.4)

```bash
uv run rag-demo index --corpus corpus/slice_v1 --encoder tei            # tier 1 (live stack: QDRANT_URL, EMBED_URL)
make fetch-tokenizer                                                     # once: pinned bge-m3 tokenizer.json (truncation count)
RAG_EMBED_TOKENIZER=$HOME/.cache/pruefstand/models/tokenizers/bge-m3.json \
  pruefstand-lock uv run rag-demo index --corpus <corpus dir> --encoder ollama   # tier 2 (OLLAMA_GPU0_URL, dev Qdrant)
uv run rag-demo index --corpus <dir> --collection pr_7_abc1234 --no-alias        # PR-scoped build, alias untouched
uv run rag-demo index --drop pr_7_abc1234                                        # executor cleanup
```

Prints `indexed N chunks into <collection>, alias chunks_active switched`. The collection is named
`chunks__<corpus_version>__<analyzer_hash8>__<embed_slug>`; an aborted build never reaches the alias. Every build writes a fresh collection and moves the alias last (the app serves the alias `chunks_active`, `RAG_COLLECTION`). `QDRANT_API_KEY` is
sent as `api-key` when set. Without `--config` the profile of `--encoder` is used (`configs/rag.yaml` or `rag.gpu.yaml`).

## Tests

`tests/unit` (pure functions on real slice text, respx for HTTP plumbing, vcr cassettes recorded from the real
llama.cpp and TEI servers by `make cassettes` and from `rerank-cpu` by `make cassettes-rerank`), `tests/contract` (OpenAPI), `tests/integration`
(Testcontainers: Qdrant with an API key, TEI, `rerank-cpu` built from `infra/gpu/rerank`), `tests/live` (the running `live` stack), `tests/gpu` (the tier-2 dev stack, marker `gpu`).

## Open follow-ups

- Ollama embeddings (`OllamaDenseEncoder`, `/api/embed`) and the bge-m3 index: T3.4. Finishing `OllamaChatGenerator` (tokenizer budget, citations): T3.6.
- Build and Trivy-scan the rag-demo image in `build-images.yml`, push and sign it: T6.2b (`push-sign`).
- Check the TEI weights SHA-256 (`live-models.yaml` `weights_sha256`) in the live stack, not only in the integration fixture: T1.12.
- Measure the p95 margin (14.2 s against 15 s on the VM) and the guard-on injection result on the hosted runner: T1.12.

## Analyzer (T3.3)

`rag_demo.analysis.analyzer.GermanAnalyzer` is used identically at index and query time. Pipeline: NFC and
lowercase, function abbreviations (`Abs.` -> `absatz`, `Nr.`, `ggf.`, `i.V.m.`; law abbreviations such as `BGB`
stay), German numbers (`1.000,50 €` -> `1000.50`, `eur`), tokeniser (keeps `§`, `622`, `626a`), Snowball
German stopwords, compound split (the compound **and** its parts; only words of 10 to 60 letters that the
shipped lexicon `analysis/lexicon_de.txt` covers completely, linking elements `s es n en e er ens`), ä/ö/ü/ß
folding, Snowball German stemming. The three switches live in the `analyzer:` section of `rag.yaml`
(`compound_split`, `fold_umlauts`, `stemmer`; defaults `true`, `true`, `snowball_de`) and are part of
`config_hash`; `compound_split: false` is mutation M4. `SparseEncoder` hashes a token to
`xxhash64(token) mod 2**31` and weights it with BM25 term-frequency saturation (k1 1.2, b 0.75); Qdrant applies
the IDF. The Indexer stores `avgdl` and an analyzer fingerprint in the collection metadata; the app refuses a
collection with a missing or different fingerprint (503, "re-index"). The served collection is the alias `chunks_active`; the snapshot file is named `slice_v2`.

`uv run python -m rag_demo.analysis.analyzer "Kündigungsschutzgesetz"` prints the token list.
Benchmark (`uv run pytest -m slow apps/rag-demo/tests/unit/analysis/test_benchmark.py -s`): 10 000 chunks
tokenised and encoded in well under the 20 s limit on CPU.
