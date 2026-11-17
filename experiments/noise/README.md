# Noise study and thresholds (T6.3)

| Module | What | Status |
| --- | --- | --- |
| `check_consistency.py` | `pruefstand.yaml` gate block equals the SPEC §5.6 defaults (S3) | done |
| `analyze.py` | sigma_d per metric x gated slice (cluster-aware, pooled per kind and arm), MDE table with the 1.5 delta check and the cluster quota (S2 core, D1275) | core done |
| `replay.py` | A/A replay of the full gate with a measured sigma_d, Wilson CIs (S2b core, D1275) | core done |
| `noop.py`, `run_noise.py` | no-op (`reindex`, `reorder`, `rebuild`), churn (`prompt_synonym` = N04, `quant_swap` = N09, `temp03`) and repeat variants of `rag.gpu.yaml`, and the per-arm run plan (`runs/noise/<arm>/plan.json`, D1277) | plan done; running needs T6.2b |
| `cause_switches.py`, outputs | the weekly cause switches, `results/noise/*.csv` | open (need T6.2b) |
| `outputs.py` | paired diffs with the gate's pairing and slices, `mde.csv` rows (one per metric x slice x split), writers for `results/noise/{sigma,mde,replay,timings}.csv` and `paired_diffs.parquet` (< 1 MB) (S5, D1280) | writers done; the files need the runs |

Tests: `uv run pytest experiments/noise/tests -q` (offline).
