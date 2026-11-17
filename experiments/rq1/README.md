# RQ1: how much do German perturbations hurt RAG? (T7.3)

Status: offline parts only (D1260, D1265, D1270). The grid runs wait for T6.2b (orchestrator collections);
e5 runs on the VM CPU TEI service (D1263); the fixed-token chunking option exists since T3.4b.

| Module | What | Status |
| --- | --- | --- |
| `evidence_recall.py` | `normalise_span`, `evidence_recall`: span-level retrieval metric (X3.2), experiment only, never gated | done |
| `volume.py` | `take_until_budget`: equal retrieved text volume (4 096 tokens) for the chunking arms (P3.2) | done |
| `grid.yaml`, `grid.py` | 12-config grid (2 embedders x dense/hybrid x 2 chunkings x compound split; 18 with `--extended`), `apply_overrides` (D1270) | done |
| `plan.py` | rq1 cases only, seeded correctness subsample, `/v1/query` vs `/v1/retrieve` plan, night-window refusal (D1270) | done |
| `run_grid.py` | every grid cell as `rag.gpu.yaml` + overrides, the `bge_m3` embed section derived from main's `rag.gpu.yaml` (D1272, D1282), validated with rag-demo's `parse_config`, written to `runs/rq1/<hash>/rag.yaml` + `grid.json`; the index builds and runs (resume, `--cleanup`) come with the run slice | cells done; runs need T6.2b |
| `analyze.py` | `paired_diffs`, `drop_table` (cluster-mean drop, gate bootstrap CI), `fix_first` (BH q 0.10), `write_heatmap` (D1265) | done; the CLI and the e5 <= 512-token / top_k 8 sensitivity rows wait for run data |

**Reranker (open, owner decision; D1288).** Every grid cell is `rag.gpu.yaml` plus overrides and retrieves through
`/v1/retrieve`, so since D1288 (`rerank.on_retrieve: false`) the cells measure the first stage (embedding, hybrid fusion,
chunking) without the reranker. Whether RQ1 keeps that or adds an override `rerank.on_retrieve: true` is proposed in the
PR that adds this note; the run slice waits for the decision.

Tests: `uv run pytest experiments/rq1/tests -q` (offline, no network, no GPU).
