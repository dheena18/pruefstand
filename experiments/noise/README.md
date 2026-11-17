# Noise study and thresholds (T6.3)

| Module | What | Status |
| --- | --- | --- |
| `check_consistency.py` | `pruefstand.yaml` gate block equals the SPEC §5.6 defaults (S3) | done |
| `analyze.py` | sigma_d per metric x gated slice (cluster-aware, pooled per kind and arm), MDE table with the 1.5 delta check and the cluster quota (S2 core, D1275) | core done |
| `replay.py` | A/A replay of the full gate with a measured sigma_d, Wilson CIs (S2b core, D1275) | core done |
| `run_noise.py` | no-op, churn and repeat runs | open (need T6.2b) |
| `cause_switches.py`, `configs/scenario_*.yaml` | the five tier-2 cause switches: run plan (judge plan AI12-10), scenario gate configs (target metric alone on `overall`), MDE pre-check, offline check of a recorded pair (D1278) | plan and check done; runs need T6.2b |
| outputs | `results/noise/*.csv`, `paired_diffs.parquet` | open (need the runs) |

Tests: `uv run pytest experiments/noise/tests -q` (offline).
