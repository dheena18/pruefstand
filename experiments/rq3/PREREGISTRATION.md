# RQ3 pre-registration: does the statistical gate catch real regressions better than simpler gates?

Status: **pre-registered before any RQ3 mutation run** (T7.2 S0). This file is the first commit of the T7.2
branch. Every RQ3 output file records the commit SHA of the version it follows. A later change is an
**amendment**: a separate commit made before the runs it affects, listed in "Amendments" below. A change made
after any affected run is a deviation, and it is reported as one.

## 1. Question and design

RQ3 (SPEC §8): on the same baseline and candidate runs, how often does each gate variant block real
regressions (detection), and how often does it block or warn on changes that should pass (false block, false
warn)?

- **Benchmark:** the entries of `benchmarks/mutations/index.yaml` at the base commit named there. These are the
  mutations M01–M20 and the no-ops N01–N09 that are listed under `entries`.
  - Entries under `pending` are not run: M11 and N09 need models the cluster does not hold (D1269).
  - Dropped and never run: N10 (D1269) and M16b (D1273).
  - M03 is run only once its VM CPU embedder exists (D1263); until then it is reported as "not run".
- **Baseline:** the unmutated base commit, run as entry `BASE` (2 repeats), with the same tier, splits and
  judge as the entries. Every variant compares each entry against this `BASE` run, never against the store's
  `main` baseline.
- **Repeats:**
  - every no-op 3×, with production cache settings;
  - every mutation once;
  - `BASE` 2×;
  - the dose-response steps 2× each.
- **Runs that are not scored:** a run that ends with an infra error (`stop_reason="aborted"` with
  `infra_error`), with `judge_fallback`, or with `complete=False` is re-run and never scored. Re-runs are counted
  in `summary.csv` column `reruns`.
  - Exception: M16, whose aborted run with `counts.corpus_mismatch == 1` (exit 1) is scored as FAIL, that is,
    detected.

## 2. The three variants (`experiments/rq3/baselines.py`)

Every variant decides on the same run pair; only the decision rule differs.

1. **Prüfstand:** the production `evaluate_gate` with the shipped `pruefstand.yaml` policy. That is one Holm
   family over the gated (metric, slice) pairs, plus hard fails, absolute checks and the WARN band.
2. **Naive mean gate:** FAIL when the overall mean of any gated paired metric drops by more than its
   `max_drop`. There is no pairing, no bootstrap and no WARN. Hard fails and absolute checks still apply, taken
   from variant 1's report on the same runs.
3. **No-slices gate:** variant 1 with `gated_slices` reduced to `overall`.

## 3. Expectations, strata and tiers

- **Expectations** come from each entry's `mutation.yaml`: `expected.status`, metrics and slices.
  `expected.likely_cause` is compared with `GateReport.likely_cause`, codes only.
- **Strata** (one list, shared with SPEC §8):
  - `deterministic`: M07, M08, M09, M12, M16. These are caught by hard fails, absolute checks or the
    precondition, so every variant catches them by construction.
  - `statistical`: every other M entry except M20.
  - `normaliser`: M20 only. It has its own "normaliser robustness" row and is outside the detection rate.
- **Tiers** (X3.10): each entry is scored only in the tier its `tier` and `splits` declare.
  - PR-tier entries run on `smoke`, `core` and `robust_pr` with the PR judge.
  - M06 runs in the **nightly table**, in the nightly rotation shape: the refusal stratum of `full` plus
    block 0.
  - M14, M15 and M20 run in the PR tier on `core`, and also in the nightly table.

## 4. True effect and "should-detect" (round 13 P3.3)

- **Reference run:** every `statistical` mutation's true effect is measured on a reference run of all three
  blocks plus the refusal stratum of `full` (`--split full --stratum all`, no block), with **3 seeds**. Each seed
  is paired with a **matched `BASE` re-run** of the same shape and seed, made for that mutation; there is never
  one shared baseline.
- **Estimate:** Δ̂_true is the mean over seeds of the paired cluster-bootstrap mean drop on the expected metric,
  with its 95 % CI.
- **Rule:** a mutation is **should-detect** iff Δ̂_true ≥ δ, where δ is that metric's `max_drop` in the shipped
  policy. This rule is fixed here, before any run.

## 5. Outcomes

- **Detection = FAIL**, for every mutation, M17 included. WARN is reported separately and never counts as
  detection.
- **Primary outcome:** the detection rate on the **should-detect `statistical` mutations of the PR tier**, for
  each variant, with Wilson 95 % CIs. **The headline comparison of variant 1 with variants 2 and 3 is on this
  stratum only;** the pooled number is secondary.
  - A `statistical` mutation with Δ̂_true < δ goes to its own table: "correctly passed" versus "flagged
    anyway". It is not a miss.
- **Also reported:**
  - the `deterministic` detection row;
  - the `normaliser` PASS row;
  - the nightly table.
- **False block** = a no-op yields FAIL. **False warn** = a no-op yields WARN.
  - These are reported for all no-ops, and separately for the `cache_invalidating` no-ops.
  - 3 repeats each give the real-run validation arm. With Wilson CIs, 0 of 30 still has an upper bound of
    about 0.11.
- **A/A replay arm (primary false-alarm estimate):** at least 500 synthetic no-op pairs per variant, resampled
  from the cached responses and judgments of the main baseline. The arm runs twice: once with σ_d(no-op) and
  once with σ_d(churn), both measured in T6.3 (`results/noise/mde.csv`).
  - The σ_d(no-op) arm is the **primary** false-block and false-warn outcome.
  - The 30 real no-op runs must lie inside its 95 % interval; otherwise the deviation is reported.
- **Dose-response:** `top_k` ∈ {8, 6, 4, 3, 2}, plus `reranker: off` at each step, 2 repeats each, run in tier 2.
  The variants are compared at a matched false-block rate of about 5 %.
- **likely_cause validation:** for every mutation with an `expected.likely_cause`, record whether it matches.
  Only the threshold constants in `gate/cause.py` may be tuned afterwards, in a separate follow-up PR that cites
  these results.

## 6. GPU-time plan and run calendar

- Before the first dispatch, an amendment records:
  - the estimated GPU hours, from T6.3's measured timings (`results/noise/timings.csv`);
  - the calendar.
  T6.3 has not run yet, so these numbers are not here yet.
- Dispatch limits:
  - never inside the night window 22:00–06:00 Europe/Berlin (D223);
  - at most 4 bench runs per weekday, the rest on weekends;
  - repeats are never cut ad hoc. A cut changes the pre-registered analysis and is reported as a deviation.

## 7. Reporting rule

All results are reported, whatever they show, including if the naive gate detects more than Prüfstand.

## Amendments

None yet.
