# Statistics notes — how the gate decides (T1.6)

Source: `packages/pruefstand/src/pruefstand/gate/` (`stats.py`, `correction.py`, `decision.py`). The rule is
SPEC §7.2, the reasoning ADR-0007. Everything here is pure: numbers in, decision out.

## Paired cluster bootstrap

`diffs[i]` = candidate − baseline for case *i*, oriented so that **negative = worse**. Cases from one source document
share a `cluster_id` and are not independent, so the bootstrap resamples whole clusters: each replicate draws *k*
clusters with replacement (*k* = number of distinct clusters) and takes the **mean over all their cases**. The estimand
is the mean over cases (every case has weight 1); clusters are only the resampling unit. With 10 clusters of 10
identical cases the CI is far wider than with 100 singletons (test `test_bootstrap.py` (h)).

**Small-sample correction.** The plain percentile bootstrap is anti-conservative for small *k* (about 0.032 instead of
0.025 at *k* = 30, from Student-t tails). Every replicate's deviation from the observed mean is multiplied by
`c_k = sqrt(k/(k−1)) · t(k−1, 1−α) / z(1−α)`: c₃₀ ≈ 1.061, c₃₀₀ ≈ 1.006, c₁ = 1. Then
`p = (1 + #{replicate ≥ 0}) / (B + 1)` for H0 "no drop" (Δ ≥ 0), `se` = standard deviation of the corrected replicates.

**How α maps to the CI.** The decision uses a one-sided level α = 0.025 (the p-value). The displayed CI is a separate
two-sided percentile interval at `confidence` (default 0.95, i.e. 2.5 % in each tail, the same tail mass as α); it is
display only and never changes a decision.

**Sign-test fallback.** With fewer than 10 clusters whose mean difference is non-zero (sparse binary metrics), the
bootstrap p has too little resolution; `p` is then the exact one-sided sign test on the non-zero cluster means:
`P(X ≤ n_pos)`, `X ~ Binomial(m, 0.5)`. Six clusters worse, none better: p = 0.5⁶ = 0.015625. CI and `se` remain the
corrected bootstrap's. A cluster mean within 1e-12 (relative) of 0 counts as zero (D344).

**Bounded work.** `n_resamples` ≤ 10 000 000 and `n_resamples × n_clusters` ≤ 1e10, the index array is chunked at 5e7 elements (the result does not depend on
the chunk size), and every invalid input (NaN/inf, empty or mismatched arrays, non-numeric parameters, float64
overflow) raises `GateInputError`; nothing returns NaN silently.

## "Significant AND relevant"

A drop fails the gate only if it is **significant** (the Holm-adjusted p is below α: unlikely to be noise) **and**
**relevant** (the mean drop exceeds `max_drop` δ: big enough to matter). A tiny but certain drop passes; a big but
uncertain one (p ≥ α) does not fail. WARN uses the looser `warn_p` (0.10) with the same relevance test. Too few
clusters give `INSUFFICIENT_DATA`; informational slices (`gated=False`) always PASS. Absolute checks use the Wilson
95 % **lower** bound against `max_value` (FAIL) and `max_value / 2` (WARN): 3 events in 120 (2.5 %) pass a 2 % limit
because the lower bound is 0.9 %.

## Holm and Benjamini–Hochberg (worked)

Raw p = [0.01, 0.04, 0.03, 0.005], m = 4. Holm sorts ascending and multiplies by 4, 3, 2, 1:
0.02, 0.03, 0.06, 0.04 → running maximum 0.02, 0.03, 0.06, 0.06 → in original order **[0.03, 0.06, 0.06, 0.02]**.
BH multiplies by m/rank from the top with a running minimum: **[0.02, 0.04, 0.04, 0.02]** (informational slices only).

## Power and minimum detectable effect

FAIL needs mean < −max(δ, z·se) with z = z₁₋α/m and se = σ_d/√n, so
`power = Φ((true_drop − max(δ, z·se)) / se)` (one case per cluster; `true_drop` defaults to 2δ).
`MDE = max((z₁₋α/m + z_power)·se, δ + z_power·se)`: the first term is what significance needs, the second what
relevance needs. Example: se = 0.0144, α = 0.025, δ = 0.03, power 0.8 → max(0.04034, 0.04212) = **0.04212** (δ binds);
se = 0.05 → max(0.14008, 0.07208) = **0.14008** (significance binds). *m* is the size of the run's single Holm family.

## Simulation results (testing-strategy §3.4)

`tests/simulation/test_gate_error_rates.py`, seed 20261027, B = 400, δ = 0.03, α = 0.025, m = 1, ICC 0.3,
`PRUEFSTAND_SIM_GRID=full` (4 000 simulations per cell). Bound for type-I: α + 3·SE = 0.03241.
FAIL rate at Δ = 0 (two cases per cluster):

| Gaussian σ_d \ n clusters | 30 | 50 | 300 |
| --- | --- | --- | --- |
| 0.15 | 0.0223 | 0.0235 | 0.0000 |
| 0.25 | 0.0263 | 0.0285 | 0.0055 |
| 0.40 | 0.0253 | 0.0253 | 0.0213 |

| Binary discordance \ n clusters | 30 | 50 | 300 |
| --- | --- | --- | --- |
| 0.02 | 0.0000 | 0.0005 | 0.0000 |
| 0.05 | 0.0018 | 0.0040 | 0.0000 |
| 0.10 | 0.0055 | 0.0170 | 0.0088 |

Heterogeneous sizes (40 clusters × 10 cases + 180 × 1): 0.0255. Power, Gaussian σ_d = 0.25, n = 300, Δ = −2δ:
**0.996** (two cases per cluster) ≥ 0.80. Formula check (one case per cluster, Δ = −2δ; observed vs `power_estimate`,
tolerance ±0.05):

| σ_d | n | observed | formula |
| --- | --- | --- | --- |
| 0.15 | 50 / 300 | 0.777 / 1.000 | 0.807 / 1.000 |
| 0.25 | 50 / 300 | 0.381 / 0.980 | 0.396 / 0.981 |
| 0.40 | 50 / 300 | 0.181 / 0.728 | 0.184 / 0.738 |

The reduced grid (every PR, 500 simulations, type-I bound 0.0529, power ≥ 0.728, formula ±0.139) passes with a maximum
type-I rate of 0.034. The per-cell file `build/simulation/power_curves.csv` (columns `kind, sigma_d, discordance,
n_clusters, cluster_size, true_drop, fail_rate, warn_rate, power_estimate`) is written by both grids.
