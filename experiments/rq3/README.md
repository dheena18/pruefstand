# RQ3: the gate benchmark (T7.2)

Pre-registration: [`PREREGISTRATION.md`](PREREGISTRATION.md), committed before any RQ3 run.

| Module | What | Status |
| --- | --- | --- |
| `baselines.py` | variant 2 `naive_gate` (overall mean drop > `max_drop`; hard fails and absolute checks from the production report) and variant 3 `no_slice_gate` (production statistics on `overall` only) | done (offline) |
| `score.py` | `summarise`: detection (FAIL only) on should-detect `statistical` mutations, WARN apart, below-delta rows, `deterministic` and `normaliser` rows, false block / false warn on no-ops, Wilson 95 % CIs, per variant and tier | core done (offline) |
| `run_all.py`, `true_effect.py`, `dose_response.py`, `replay.py` | executor bench runs, the true-effect reference, dose-response, the A/A replay arm | open (need T6.2b, T6.3) |

Tests: `uv run pytest experiments/rq3/tests -q` (offline, no network, no GPU).
