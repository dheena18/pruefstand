# Noise study and thresholds (T6.3)

| Module | What | Status |
| --- | --- | --- |
| `check_consistency.py` | `pruefstand.yaml` gate block equals the SPEC §5.6 defaults (S3) | done |
| `analyze.py` | sigma_d per metric x gated slice (cluster-aware, pooled per kind and arm), MDE table with the 1.5 delta check and the cluster quota (S2 core, D1275) | core done |
| `replay.py` | A/A replay of the full gate with a measured sigma_d, Wilson CIs (S2b core, D1275) | core done |
| `run_noise.py`, `cause_switches.py`, outputs | no-op, churn and repeat runs, the weekly cause switches, `results/noise/*.csv` | open (need T6.2b) |

Tests: `uv run pytest experiments/noise/tests -q` (offline).
