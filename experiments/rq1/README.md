# RQ1: how much do German perturbations hurt RAG? (T7.3)

Status: offline parts only (D1260, D1265, D1270). The grid runs wait for T6.2b (orchestrator collections);
e5 runs on the VM CPU TEI service (D1263); the fixed-token chunking option exists since T3.4b.

| Module | What | Status |
| --- | --- | --- |
| `evidence_recall.py` | `normalise_span`, `evidence_recall`: span-level retrieval metric (X3.2), experiment only, never gated | done |
| `volume.py` | `take_until_budget`: equal retrieved text volume (4 096 tokens) for the chunking arms (P3.2) | done |
| `grid.yaml`, `grid.py` | 12-config grid (2 embedders x dense/hybrid x 2 chunkings x compound split; 18 with `--extended`), `apply_overrides` (D1270) | done |
| `plan.py` | rq1 cases only, seeded correctness subsample, `/v1/query` vs `/v1/retrieve` plan, night-window refusal (D1270) | done |
| `run_grid.py` | builds/reuses the collections, runs the grid, resume, `--cleanup` | open (needs T6.2b) |
| `analyze.py` | `paired_diffs`, `drop_table` (cluster-mean drop, gate bootstrap CI), `fix_first` (BH q 0.10), `write_heatmap` (D1265) | done; the CLI and the e5 <= 512-token / top_k 8 sensitivity rows wait for run data |

Tests: `uv run pytest experiments/rq1/tests -q` (offline, no network, no GPU).
