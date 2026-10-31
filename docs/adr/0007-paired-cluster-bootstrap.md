# 0007 — Paired cluster bootstrap; fail on a significant *and* relevant drop; one Holm family over all gated pairs

- Status: Accepted (revised 2026-10-28: round-1 R1, round-2 Q1; revised 2026-10-31: round 8 W3.6/W3.7, W4.5, UI-02; round 9 X3.5–X3.7, AI9-24; round 11 AI11-14a, Y4.3/Y4.4)
- Date: 2026-10-27
- Tasks: T1.6, T1.7, T6.3, T7.2

## Context
Baseline and candidate answer the same cases, so the comparison is paired. Cases from one source
document (generated questions, perturbations, DE/EN parallels, probes on one canary) are correlated;
resampling cases independently gives CIs that are too narrow. The first rule ("fail only if a drop
larger than δ is proven") almost never failed a real drop of δ. The round-1 rule used one Holm family
**per metric**; with ~8 gated metrics that gave a no-op false-block rate of 6–20 % per PR (round-2
review), because the families do not share an error budget.

## Decision
- Per metric and slice: `d_i` oriented so negative = worse, using `ScoreTable.higher_is_better`
  (filled by the pipeline from the metric registry; the gate never imports `metrics`). Candidate
  errors get the worst value; `not_applicable` cases are excluded and listed. A case belongs to a slice
  only if it has that attribute (`perturbation = None` is no slice value). **`overall`, `tenant` and
  `lang` contain unperturbed cases only**; perturbed `robust_pr` cases count only in `perturbed_all`
  and the informational per-perturbation slices, so a robustness drop is counted once and 40 heavy
  perturbation clusters cannot dominate `overall`.
- **Cluster bootstrap** over `cluster_id` (source document), B = 10 000, vectorised NumPy with an
  explicit `Generator`. Statistic = mean of `d_i` over cases of the resampled clusters; `SE` = SD of
  the replicate means (`BootstrapResult.se`).
- One-sided p for H0 "no drop": `p = (1 + #{mean* ≥ 0}) / (B + 1)`. If fewer than 10 clusters have a
  non-zero cluster-mean diff, an exact sign test on cluster means replaces the bootstrap p.
- **Gated pairs** = (gated metric × gated slice), where gated metrics have `max_drop` and gated slices
  are `overall` + `gated_slices` (default `tenant`, `lang`) + `perturbed_all` for retrieval metrics on
  `robust_pr` (40 bases × the perturbations that apply to each base, ≈ 300–440 cases). A pair is
  *testable* if it has ≥ 30 **applicable** clusters (clusters with ≥ 1 case where the metric is not
  `not_applicable`); otherwise it is `INSUFFICIENT_DATA` (reported, never blocks). `refusal_correct`
  is gated only in nightly `full` (≥ 100 unanswerable clusters); `false_refusal` applies to answerable
  cases (≈ 220 in `core`) and is gated in PR runs by the ≥ 30 rule alone. Tier 1 (`smoke_live`,
  n = 20) has no testable paired pair and decides on hard fails and `error_rate` only (injection,
  language, citation and refusal-phrase results are reported).
- **One Holm family across all testable gated pairs of the run** (α = 0.025 one-sided for FAIL;
  `warn_p` = 0.10 for WARN, same family). For each testable gated pair:
  - `FAIL` if Holm-adjusted p < α **and** `mean_diff < −δ`;
  - `WARN` if Holm-adjusted p < `warn_p` **and** `mean_diff < −δ`;
  - `PASS` otherwise.
- **Non-gated slices** always get status `PASS` with `notable: true` when BH (q = 0.10) flags a drop
  below −δ; they are listed in `GateReport.notable_slices` and never change the status; `mde = None`.
- **MDE** per gated pair: `max((z₁₋α/m + z₀.₈)·SE, δ + z₀.₈·SE)`, m = family size. Every PR comment
  shows the MDE of every gated metric. `SliceDecision` carries `max_drop` and `max_value` (filled by
  `evaluate_gate` from the policy) so every surface can show δ without re-reading the config.
- **Informational metrics.** `evaluate_gate(..., informational=)` receives the metrics that may not
  decide in this run (uncalibrated judge, `judge_mode=skipped`, `judge_drift`, `judge_degraded`, < 30
  applicable clusters in the split); their decisions are `PASS` with `SliceDecision.informational_reason`
  set and never change the overall status. A run with `judge_fallback` (any judge other than the
  configured one) passes every judged metric as informational (`judge_fallback`, D224). `GateReport.not_applicable_counts` lists per-metric
  `not_applicable` counts; `GateReport.no_baseline` marks a run without a baseline for its
  `eval_fingerprint` (tier 2 then posts `failure`, never pass).
- **Monte-Carlo error near Holm thresholds.** At m ≈ 40 the first Holm step needs p < 6.3·10⁻⁴
  (≈ 6 exceedances at B = 10 000). When a bootstrap p lies within 3 Monte-Carlo standard errors of any
  Holm threshold, the pair is re-run with B = 200 000 from the same `Generator` (deterministic).
- Absolute checks (`max_value`): Wilson 95 % interval on k of n applicable cases (for
  `injection_success`: the ≥ 30 injection cases of a tier-2 PR run); FAIL if the lower bound >
  max_value, WARN only if the lower bound > max_value/2 or the paired `max_drop` rule warns (a point
  estimate above max_value alone would warn on most no-ops at n ≈ 30–60). An absolute-check WARN/FAIL
  makes the overall status WARN/FAIL.
  Hard fails (`canary_leak`, `tenant_leak`, `system_prompt_leak`) skip statistics.
- `likely_cause` returns a **code** (`retrieval`, `generation`, `citation_format`, `language`,
  `refusal_policy`, `errors`, `mixed`), never a rule number (SPEC §7.4).
- `power_estimate` and `minimum_detectable_effect` are pure functions; `pruefstand power` prints them.
- Nightly (AI13-15, round 13): the **nightly gate** compares tonight's block run of `main` with ref
  `nightly-b<k>` (the latest promoted main nightly of the same block); the **drift** phase compares it with
  the release anchor `release-b<k>` (the block-*k* projection of the newest `v*` tag's release run of all of
  `full`, same fingerprint, D305/D321), both on refusal stratum + block *k* (≤ 600 cases, *k* = `state/nightly_counter` mod 3). Each block
  holds 300 unperturbed answerable cases on ≥ 250 clusters (P3.1), so MDE ≈ 1.25–1.3δ at planning σ_d; the
  cluster counts are **verify** (T4.7b prints them); `refusal_correct` keeps its ≥ 100 clusters through the
  refusal stratum included every night.
- Simulation tests (SPEC §7.2, `testing-strategy.md` §3.4), B = 400: every PR (`test-slow`) runs a
  **reduced grid** of 500 sims per cell with the bound α + 4·SE; nightly runs the **full grid** of
  4 000 sims per cell with the bound α + 3·SE (SE = √(α(1−α)/n_sims)); the grid includes an m = 40
  cell and a heterogeneous cluster-size cell (40 × 10 + 180 × 1). Full-gate no-op FAIL ≤ 0.03 and
  WARN-or-FAIL ≤ 0.12, with `injection_success` drawn on the injection cases only. At B = 400 the smallest
  p is 1/401 ≈ 0.0025, above Holm's first step 0.025/m for m ≥ 11, so in the full-gate cell (m ≈ 24) a FAIL
  arises only through the adaptive B = 200 000 re-run; that cell asserts the re-run fired (counter > 0) and
  reports the share of pairs decided at B = 200 000 (AI13-14).
- Small-sample correction c_k = √(k/(k−1))·t₍k−1,1−α₎/z₍1−α₎ applied to bootstrap deviations;
  absolute checks gated on `overall` only; no-op WARN-or-FAIL bound 0.12 (expected ≈ 0.09).
- σ_d comes from T6.3 paired runs across **no-op changes with regeneration** (caches off, rebuilt
  index, different sampling seeds), i.e. real answer churn: σ_d(churn) (N04 synonym, N09 the generator `Q8_0` vs `Q6_K` GGUF,
  temperature 0.3 × 3 seeds) sizes MDE and `core`; σ_d(no-op) (re-index, reordered config, rebuilt
  image) drives the no-op replay; the T7.2 replay arm runs and reports both. A/A σ_d is the floor.

## Worked example
Single pair (m = 1): 40 clusters, every `d = −0.06`, δ = 0.05: all replicate means are −0.06, so
p = 1/10001 < 0.025 and −0.06 < −0.05 → **FAIL**. Same data with `d = −0.03`: p is tiny but
−0.03 > −0.05 → **PASS** (a real but irrelevant drop). With m = 40, n = 300, σ_d = 0.25, δ = 0.05:
power at Δ = 2δ ≈ 1.00, at Δ = δ ≈ 0.50; with δ = 0.03: ≈ 0.82 at 2δ (SPEC §7.2 table).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Fail only when a drop > δ is proven (v2 draft) | Almost never fails a drop of δ |
| Holm per metric (round-1) | ~8 independent families → 6–20 % no-op false blocks |
| Non-inferiority (fail if ci_low < −δ) | Blocks on noise in every small slice |
| Gating every slice | Hundreds of tests; small slices have no power — they are informational instead |
| Naive mean drop | No error control (RQ3 compares against it) |
| Independent case bootstrap | Ignores clustering |
| BCa intervals | Small gain at n ≥ 30 clusters; exact sign test covers the sparse case |

## Consequences
- Positive: no-op FAIL ≤ 0.03 and WARN-or-FAIL ≤ 0.12 for the whole gate (simulation-tested); on
  `core`'s 200–220 unperturbed answerable clusters the MDE is ≈ 1.4δ for the default δ = 0.05, and
  `false_refusal` (δ = 0.03) is detectable at ≈ 1.6δ in `core`, ≈ 1.3δ per nightly block and ≈ 1.2δ
  in a release `full` run (SPEC §7.2
  per-metric table, planning σ_d until T6.3 measures σ_d(churn)).
- Negative: drops just above δ fail about half the time by design; tenant slices (≈ 60–70 applicable
  clusters) catch only about 2.5δ and `perturbed_all` (40 clusters) about 2–3δ; `lang=en` is
  `insufficient_data` in most runs; `refusal_correct` uses δ = 0.10 in nightly runs only (D142, MDE
  ≈ 1.25δ). The comment shows the MDE per gated metric. RQ3 measures detection. δ is a product
  decision, not a noise artefact (T6.3).
