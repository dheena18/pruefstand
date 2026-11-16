# RQ1: how much do German perturbations hurt RAG? (T7.3)

Status: offline parts only (D1260). The grid itself waits for T6.2b (orchestrator collections), the e5
embedder on the cluster disk and the rag-demo fixed-token chunking option.

| Module | What | Status |
| --- | --- | --- |
| `evidence_recall.py` | `normalise_span`, `evidence_recall`: span-level retrieval metric (X3.2), experiment only, never gated | done |
| `volume.py` | `take_until_budget`: equal retrieved text volume (4 096 tokens) for the chunking arms (P3.2) | done |
| `grid.yaml`, `run_grid.py` | 12-config grid (2 embedders x dense/hybrid x 2 chunkings x compound split) | open |
| `analyze.py` | drops per config x perturbation with cluster bootstrap CI, heatmaps, BH fix-first list | open |

Tests: `uv run pytest experiments/rq1/tests -q` (offline, no network, no GPU).
