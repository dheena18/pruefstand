# RQ2: judge calibration (T5.4)

Can a cheap open judge replace a large one on German RAG? This directory builds the T5.3 label sets
(`build_calibration_sets.py`, T5.3) and calibrates the judges on them (T5.4).

## Reproduce

Everything runs on the VM; GPU steps under the shared lock. `OLLAMA_GPU1_URL` (judge) and, for the bias step,
`OLLAMA_GPU0_URL` (generator) point at the tunnel (`docs/ops/secrets.md`).

| Step | Command | GPU | Runtime (gemma3:12b, 4 in flight) |
| --- | --- | --- | --- |
| Degraded pairs (S3) | `uv run python experiments/rq2/make_degraded.py` | no | seconds |
| Judge the sets (S2) | `pruefstand-lock uv run python experiments/rq2/run_judges.py --judges experiments/rq2/configs/rq2_judges.yaml --seed 1234 --split test --pairs` | yes | ~ 60 min for ~ 2 400 calls; a second run prints `new LLM calls: 0` (judge cache) |
| Anchors + flip rate (S9, S11) | `pruefstand-lock uv run python experiments/rq2/anchors.py --judge ollama/gemma3:12b --repeats 4` | yes | ~ 5 min |
| Bias (S6) | `pruefstand-lock uv run python experiments/rq2/bias.py --judge ollama/gemma3:12b` | yes | ~ 15 min (loads the generator) |
| Report (S4, S5, S7, S8) | `uv run python experiments/rq2/report.py` | no | ~ 1 min |
| Re-calibration (S11) | `uv run python experiments/rq2/recalibrate.py --judge <id>` | no | after a new `run_judges.py` run |

Prompt work uses only `--split dev` (`run_judges.py --split dev --prompt faithfulness=v3`, refused on `test`);
the pass rule and every RQ2 number are computed once per prompt version on `test` (AI13-12).
The calibration renders prompts with a fixed public nonce key (`run_judges.CALIBRATION_NONCE`): the inputs are
public or local data, not attacker-written, and the judge cache stays reproducible.

Outputs: `results/rq2/{calibration,agreement_matrix,bias,discrimination}.csv`, `results/rq2/cost_vs_kappa.png`,
`results/rq2/anchor_flips.json`, `results/_inputs/rq2/verdicts.parquet` (no text, no MEMERAG),
`packages/pruefstand/src/pruefstand/judges/data/calibration_status.yaml` and
`packages/pruefstand/src/pruefstand/judges/data/anchors/ollama_gemma3-12b.jsonl`. MEMERAG verdicts stay in the
git-ignored `data/derived/memerag_de/verdicts.parquet`; the MEMERAG rows of `calibration.csv` are reproduced only
with the MEMERAG set present (`FROM_SCRATCH=1` makes their absence an error).

## Results (2026-11-10, `test` split, `ollama/gemma3:12b` Q4_K_M, digest b92b218582c5)

Prompts `faithfulness_de_v2`, `answer_correctness_de_v4`, `refusal_judged_de_v1`, `perturbation_consistency_de_v1`
(versions tried: `calibration_status.yaml`, D937). Binary kappa with 95 % cluster-bootstrap CI (2 000 resamples,
seed 1234); hard-negative specificity with its Wilson lower bound.

| Metric | Label set (origin) | n | kappa (CI) | AC1 | HN specificity (low) | Discrimination swap / negate | Pass rule |
| --- | --- | --- | --- | --- | --- | --- | --- |
| faithfulness | MEMERAG (human) | 274 | 0.25 (0.14-0.37) | 0.65 | 0.23 (0.15) | 0.62 / 0.50 | **fail** |
| faithfulness | faithfulness_constructed | 420 | 0.78 (0.72-0.84) | 0.78 | 0.65 (0.56) | (same pairs) | not gating |
| faithfulness | legal_hard | - | pending | | | | pending |
| answer_correctness | correctness (constructed) | 395 | 0.82 (0.76-0.87) | 0.82 | 0.97 (0.93) | 0.82 / 0.62 (n 21) | **fail** (discrimination) |
| answer_correctness | legal_hard | - | pending | | | | pending |
| refusal_judged | refusal | 420 | 1.00 | 1.00 | hedged FPR 0.00 | - | **pending**: reported, not a pass (near-miss set not built, D944) |
| perturbation_consistency | consistency | 573 | 0.92 (0.88-0.94) | 0.92 | 0.78 (0.65) | - | reported |

Outcome: `calibration_status.yaml` `passed: false` (judged metrics informational in both tiers; the refusal judge
stays off until its near-miss set exists), `judge_epoch` 1. Ceiling for MEMERAG (German): AC1 0.84 / Fleiss kappa 0.81
(MEMERAG paper, Table 2). Cost: USD 0, about 1 395 GPU-s and no quota per 1 000 judgments, latency p50 4.9 s / p95
9.6 s at 4 in flight. Drift anchors: 4 flips in 150 comparisons, f_upper 0.067, `drift_threshold` 9, `a0` 0.96. The 4 flips sit on only 2 anchors, so the per-anchor binomial
model overstates the spread; replacing those anchors or storing their majority verdict is a follow-up (D945).
Bias: not measurable on this sample: the T4.5 gender/register rewrites changed none of the 50 short answers (D942).
Judge (c) and the GitHub Models arms are not measured yet (hosted runner follow-up, D939); the agreement matrix
therefore has one judge.

## Limitations (hand to T9.3)

- Constructed labels have no partial credit beyond the `partial_answer` construction: a constructed answer is
  right or wrong by construction, not by a reader's judgment.
- Off-topic constructed negatives (an answer to another question) are much easier than real errors, so kappa on
  the constructed sets is an upper bound. That is why the hard-negative subset (number/date swaps, negation flips,
  partial answers, same-paragraph spans, hedged answers, MEMERAG "Not Supported") is reported and gated separately
  by specificity, never by kappa (every hard negative has the same label, so kappa there is 0 or undefined).
- MEMERAG answers come from other systems on MIRACL (Wikipedia) contexts, not from the reference app; its labels
  are human (majority of the extended annotation), but the domain is general knowledge, not law.
- `legal_hard` (T5.3 PR 2, needs T4.7b + T3.6) is not built yet: the pass rule requires it for both gated
  metrics, so no judge can be `passed` before it exists; those cells are `pending`.
- The public-text datagen family (GitHub Models, `gpt`, T4.2) differs from the gating judge family `gemma`
  (ADR-0019); only a (b') or (c) arm of that family shares it, so its `answer_correctness` agreement is reported
  separately and never used to pick a judge.
- Only one local judge was measured: the size contrast `gemma3:4b` (b'') and any (a') replacement need the
  owner's `MAINTENANCE` swap outside the night window; the GitHub Models arms (b', c) need a hosted runner
  (models.github.ai answers a bare `200 OK` on the VM). The agreement matrix therefore has a single judge.
