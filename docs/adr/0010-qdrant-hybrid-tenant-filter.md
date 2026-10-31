# 0010 — Qdrant only: dense + own German sparse vectors, in-query tenant filter

- Status: Accepted (revised 2026-10-31: round 8 AI-13/29/35, W3.10; round 9 X3.13; round 10 D198: `bge-m3` via Ollama, reranker on the VM CPU; round 11 D219/D220/D222: native Ollama API with catalogue options, reranker top 10 x 256 tokens)
- Amended by: [ADR-0018](0018-single-ollama-server.md) (2026-10-31: one Ollama server for both GPUs, port 11434 only)
- Amended by: [ADR-0019](0019-local-model-storage-small-disk.md) (2026-10-31: `bge-m3` lives on the cluster's small model disk; another embedding model (e5 for RQ1/M3) needs space next to the standard set or the swap rule)
- Date: 2026-10-27
- Tasks: T3.3, T3.4, T3.5, T7.1a

## Context
Hybrid retrieval needs BM25-like sparse search with a German analyzer (stemming, compound splitting) plus
dense search. Both must run under a tenant filter applied **inside** the search. Filtering after the top-k
cut is the classic leak bug (mutation M8). A separate BM25 engine would mean two filter paths to get right.

## Decision
- One Qdrant collection with two named vectors: `dense` (BGE-M3, cosine) and `sparse` (own analyzer → hashed vocab,
  BM25 TF weights, `modifier: idf`). In tier 2 the dense vectors come from the Ollama model `bge-m3` on
  the cluster's one Ollama server (ADR-0018; `/api/embed`, dense only; T3.1b verifies cosine ≥ 0.99 against the reference checkpoint on 20
  passages); the sparse side is always our own analyzer. Qdrant runs on the executor VM with storage
  on the local VM disk (`$PRUEFSTAND_HOME/qdrant`), never in the data root or on a network share.
- Payload index on `tenant_id` (`is_tenant: true`), plus `doc_id`, `lang` and `is_attack`.
- The Query API runs two `prefetch` branches (dense, sparse). **Each** branch carries the filter
  `tenant_id ∈ {tenant, "shared_public"}`. The branches are fused with RRF, then the optional reranker
  (`BAAI/bge-reranker-v2-m3` on the **VM CPU** in the trusted `rerank-cpu` service, sentence-transformers
  behind a TEI-compatible `POST /rerank`; tier 2 default: the **top 10** fused candidates, passages
  truncated to **256 tokens**, one batched call per query → `top_k`; tier 1 has no reranker) runs on
  the top-N. Its CPU time is a budget lane of its own (`budget.py`, SPEC §6.2), measured in T3.1b; if
  it exceeds 20 min per PR run, `robust_pr` runs with the reranker off and is reported as first-stage
  robustness (D222). `POST /v1/retrieve` (no generation; D218) runs this same retrieval path.
- Dense encoders apply each model's `query_prefix` / `doc_prefix` (e5 family: `query: ` / `passage: `)
  and `max_input_tokens`; tier 1 calls TEI (CPU) with `truncate: true`, tier 2 calls Ollama
  `/api/embed` (native API only, D219) with the catalogue `options.num_ctx` = `max_input_tokens`,
  enforced by `llm-proxy` (D220) (truncation counted by token length before
  the call); the number of truncated passages is logged (`truncated_chunks` in collection metadata and `/v1/health`; `/v1/info.serving` holds only
  static fields because it enters `target_fingerprint`).
- `GermanAnalyzer(compound_split: bool)` switches splitting on and off, so mutation M4 is a config flag.
- The pgvector option is dropped.

## Alternatives considered
| Option | Why not |
| --- | --- |
| bm25s or Elasticsearch next to Qdrant | Two filter paths and two indices to keep in sync |
| pgvector | Weaker hybrid and fusion support, and it would bring Postgres back (ADR-0003) |
| Qdrant built-in BM25 (fastembed) | No control over compound splitting |
| One collection per tenant | Cannot represent the M9 bug class (shared_public merge) and needs many collections |
| TEI on the A40 for embeddings and reranking (round-9 design) | No Docker on the cluster (round 10); Ollama serves `bge-m3`, but Ollama has no reranker endpoint, so the reranker moved to the VM CPU |

## Consequences
- Positive: there is one filter path to test, and the leak mutations are realistic code changes.
- Negative: we maintain and test our own sparse encoder. 2^31 hashed vocab (`xxhash64 mod 2^31`); the
  collision rate on the full corpus vocabulary is reported by T3.3.
- Accepted limitation of the shared collection: Qdrant `modifier: idf` computes IDF over the **whole**
  collection (all tenants, incl. private docs), so ranking depends on other tenants' term statistics
  and returned `score` values are a weak side channel. The public demo strips `score` (T8.4).
- Test: a property test checks that for random tenant pairs, no hit ever carries a foreign `tenant_id`.
