# Round 12: cold read 7 — senior AI / ML engineer lens (LLM eval, RAG, serving on the real hardware)

Scope: `REVIEW.md`, `docs/decisions.md` (active rows; D211–D247 binding, superseded rows ignored),
`docs/spec/SPEC.md`, `docs/architecture/interfaces.md`, `docs/engineering/{gpu-cluster,testing-strategy,ci-cd}.md`,
ADR-0007/0008/0009/0010/0015, `DATA_LICENSES.md`, prompts T1.4–T1.7, T1.11–T1.13, T2.*, T3.*, T4.*, T5.*, T6.3,
T7.*, plus the T6.2a/T6.2b/T0.6 passages they reference. Prior findings (`round11-ai.md`, resolved by
`round11-resolution.md` Y1–Y7 and `round11-integration.md` D242–D247) are not repeated; a row marked "R11 AI11-nn"
is a residual of that finding. Hardware judged as binding: 2 × A40 (46 068 MiB), Ollama only (`:11434` GPU0
generator `qwen3.8:27b-q8_0` + `bge-m3`, `:11435` GPU1 judges), models on the NAS, execution on the TrueNAS VM
(64 GB) through `autossh` + `llm-proxy`, tier 1 on GitHub-hosted CPU, free providers only.
Nothing was edited except this file.

## Assumptions (planning numbers, not measured; all **verify** in T0.6 / T3.1a / T3.1b)

- A40 (696 GB/s, ≈ 150 TFLOP/s dense FP16): 27B `Q8_0` prefill ≈ 900–1 300 tok/s, decode ≈ 45–60 tok/s aggregate
  at 4 slots; Mistral Small 24B `Q4_K_M` prefill ≈ 1 100–1 600, decode ≈ 80–110 aggregate; Gemma 3 27B `Q4_K_M`
  prefill ≈ 900–1 300, decode ≈ 60–90 aggregate; Llama 70B `Q4_K_M` layer-split ≈ 35–45 tok/s aggregate decode.
- KV per token (f16): Mistral Small 3.x 40 L × 8 KV × 128 → 160 KiB; Gemma 3 27B 62 L × 16 KV × 128 → ≈ 0.48 MiB
  without a sliding-window cache, ≈ 90–110 KiB effective with it; Llama 3.3 70B → 320 KiB; `qwen3.8:27b` unknown
  (planning 256 KiB). Ollama allocates `num_ctx × OLLAMA_NUM_PARALLEL` per loaded model, embedding models included
  (**verify** for the `bert`/XLM-R runner).
- Ollama: per-request sampling options (`temperature`, `seed`, `top_p`, `num_predict`) do **not** force a reload;
  load-time options (`num_ctx`, `num_gpu`, `num_batch`, …) do (**verify** on the pinned version).
- `bge-reranker-v2-m3` on 8 vCPU fp32, 10 pairs × ≈ 290 tokens ≈ 1.5–5 s per query (≈ 0.18 TFLOP per pair);
  ONNX int8 ≈ 2–3× faster.
- NAS throughput unknown (T0.6 C6): at 1 GbE generator ≈ 4.5 min, judge ≈ 2–2.5 min, 70B ≈ 6.5 min per load.
- MDE = max(4.07·SE, δ + 0.84·SE), SE = σ_d/√n_clusters, m ≈ 40 (SPEC §7.2).

## Findings

| ID | Sev | File:line | Problem | Why it matters | Exact fix |
| --- | --- | --- | --- | --- | --- |
| AI12-01 | major | `docs/architecture/interfaces.md:281` (`Split`), `:394-404` (`eval_fingerprint`), `:1059-1061` (`DatasetManifest`), `:1102`/`:1113` (`run_eval`, `pruefstand run`); `prompts/T6.2b-gate-workflows.md:110,144`; `docs/spec/SPEC.md:779-785,1034-1036`; `docs/engineering/ci-cd.md:263`; `prompts/T6.3-noise-thresholds.md:132` | The D223 nightly rotation (refusal stratum + block *k* mod 3) and the D199 150-case judged subset exist only in prose. No contract carries them: `Split` has no block, `DatasetManifest` has no strata/block/subset field (T6.3 S4 and T6.2b read "the dataset manifest's nightly strata, T4.7b", which T4.7b does not build), `eval_fingerprint` has no block parameter although T6.2b says "the block id is part of the fingerprint", and `run_eval`/CLI cannot select a block. The baseline is also defined three ways: SPEC §6.2 "each night compares `main` with the `release` baseline", T6.2b "previous nightly **of the same block**" + a `drift` job vs `--ref release`, ci-cd "vs nightly main baseline". With the block in the fingerprint, `--ref release` is promoted only from "the first nightly after a new release tag", i.e. for **one** of three blocks; the release-branch run of all of `full` has a different fingerprint. | Implemented literally (fingerprint without block), `--from-store --ref main` returns the previous night = another block; step 1 "align by case_id" leaves only the refusal stratum, so every answerable pair is silently `insufficient_data` (or `GateInputError`). With the block in the fingerprint, the cumulative-drift check (SPEC §7.2) has a baseline on ≤ 1/3 of nights per release. The judged-subset fallback has the same hole. | Add `DatasetManifest.strata: dict[str, tuple[CaseId, ...]]` (keys `refusal`, `block_0..2`, `judged_subset_150`), built and validated by T4.7b (whole clusters, union = `full`). `run_eval(..., case_filter: str \| None)` + CLI `--subset block_k\|judged_subset_150`; `RunManifest.subset: str \| None`. **Do not** put the block in `eval_fingerprint`; instead the gate aligns on case ids and requires `candidate ⊆ baseline` (else `GateInputError`). Then: nightly-gate = vs the newest nightly baseline restricted to tonight's ids (any block that covers them, i.e. the same block 3 nights ago), drift = vs the release-branch run of **all** of `full` restricted to tonight's ids (one release baseline serves every block). Pick one wording and fix SPEC §6.2/§7.2, ci-cd §2.3, T6.2b, T6.1 (`BaselineStore.get` unchanged), T1.6 (subset alignment test), test-matrix. Optional: a weekly pooled test over the three latest block runs (≈ 1/1 of `full`, MDE ≈ 0.057). |
| AI12-02 | major | `prompts/T6.2a-gate-executor.md:136,307`; `docs/decisions.md` D220; `prompts/T3.6-generator.md:38-42`; `prompts/T7.1b-mutations-extended.md:32-34,65`; `prompts/T6.3-noise-thresholds.md:56-62,128`; `docs/spec/SPEC.md:1336` (M17) | Y3.2/D220 makes `llm-proxy` replace **all** client `options` with the catalogue values (test: `temperature: 0.9` → forwarded as catalogue), and rag-demo's tier-2 client sends "exactly the catalogue options". So in every gate run: M17 (generation temperature 0 → 0.7, a `kind: code` patch) is silently reverted → a guaranteed "miss" in the RQ3 detection rate; T6.3's churn arm `temp03` and the no-op runs' "generator seed = seed + run index" become identical re-runs → σ_d(churn) is underestimated → MDE and the A/A replay false-block rates are optimistic; `max_tokens` in `rag.gpu.yaml` is dead while the candidate computes its prompt budget from it (`num_ctx − num_predict`). | RQ3 headline biased downward by construction; the noise study that sizes every MDE measures the wrong churn; a PR that changes generation length or temperature is gated against an unchanged generator. | The reload risk comes only from **load-time** options. `llm-proxy` forces `num_ctx` (and strips `num_gpu`, `num_batch`, `num_thread`, `use_mmap`, `main_gpu`, `low_vram`, any other load-time key) but passes `temperature` ∈ [0, 1], `seed`, `top_p`, `num_predict` ≤ catalogue max through; rag-demo sends them from `rag.gpu.yaml` (`generation.temperature`, `seed`, `max_tokens`), which enter `config_hash` → target fingerprint. Update D220 text, interfaces §1.5, T6.2a test (`temperature: 0.9` → forwarded; `num_ctx: 65536` → catalogue; `num_gpu: 0` → stripped), T3.6, T6.3 (assert two `temp03` seeds give different answers on ≥ 10 % of cases). Judges keep fully fixed catalogue options (trusted client). |
| AI12-03 | major | `prompts/T5.4-judge-calibration.md:96-99,183,186`; `docs/architecture/interfaces.md:623-627`; `docs/spec/SPEC.md:499,1220`; `docs/decisions.md` D246 | Local-judge drift = one-sided binomial test of tonight's anchor agreement against `a0`, where `a0` is the self-agreement of **one** double-judging of the same 50 anchors. At temperature 0 a re-judge is often identical, so `a0 = 1.0` is likely (true flip rate 2 % → P(50/50) ≈ 0.36). Against p₀ = 1.0 any single flip gives p = 0 < 0.01 → drift. With a true flip rate f, P(alarm per night) = 1 − (1 − f)^50 ≈ 0.64 at f = 0.02, 0.92 at f = 0.05. Even `a0 = 0.98` (1 flip) is a noisy point estimate that alarms every few weeks. No test covers `a0 = 1.0`. | Frequent false drift: judged metrics informational on PRs and nightlies, a judge-cache invalidation each time (every baseline/candidate verdict re-judged), "cleared by a passing re-run" only on a later night. | T5.4 S11: judge the anchors **≥ 4 times** at production concurrency (≥ 200 paired comparisons, plus 200 calibration items if cheap) and store disagreement counts `(k0, n0)`. Drift iff a one-sided **two-sample** test (Fisher exact) of tonight's disagreements vs `(k0, n0)` gives p < 0.01 **and** tonight's disagreements ≥ 4. `is_drift(agreement, n, *, a0=None, k0=None, n0=None)`; tests: `a0 = 1.0, 1 flip` → False; `(k0, n0) = (4, 200)`, 12/50 flips → True. Update interfaces §6, D246, SPEC §5.4/§7.5, test-matrix. |
| AI12-04 | minor | `docs/architecture/interfaces.md:355,375-380,1218-1222`; `docs/engineering/gpu-cluster.md:161,214,229-230`; `docs/ops/runbook.md:154`; `docs/ops/secrets.md:75`; `docs/decisions.md` D198 (R11 AI11-09, AI11-10, AI11-14c/d residuals) | Round-11 fixes landed in ADR-0006/0009, SPEC, T3.1a, T5.1, T5.4, T7.1b but not in the contract and ops files: interfaces still defines `judge_serving` as `"<engine> <engine_version> <quantization>"` (no `digest[:12]`) in `RunManifest` and the §17 formula, and the `judge_drift` comment still states only the hosted rule; gpu-cluster §2.1/§4, runbook and secrets.md still set `OLLAMA_KEEP_ALIVE=24h` and omit `OLLAMA_NOPRUNE=1` / `OLLAMA_KV_CACHE_TYPE=f16`; gpu-cluster §4 preload is `POST /api/generate {model, keep_alive}` **without** the catalogue `options` (contradicts Y3.2; the first real request would reload). | T1.1 implements `eval_fingerprint` from interfaces; agents following gpu-cluster/runbook build the old env and the reload-prone preload. | Copy the digest form into interfaces `:355` and `:1218-1222`; update the `judge_drift` comment to point at §6 `is_drift` (both rules); gpu-cluster §2.1/§4, runbook §2, secrets.md: `OLLAMA_KEEP_ALIVE=-1` (**verify**, else `24h`), `OLLAMA_NOPRUNE=1`, `OLLAMA_KV_CACHE_TYPE=f16`; preload body = `{model, keep_alive, options: <catalogue>}`; annotate D198 "env refined by T3.1a/ADR-0009". |
| AI12-05 | minor | `docs/spec/SPEC.md:1092,1095-1100,779-783`; `prompts/T6.3-noise-thresholds.md:70-71` | (a) Release `full` judged MDE "≈ 0.050–0.054 (≈ 1.05δ)" is impossible under the stated rule: MDE ≥ δ + 0.84·SE > δ; at 1 000 clusters it is 0.057 (1.13δ), at 700 0.058. (b) Block size "≈ 330 answerable clusters" assumes ≈ 1 000 answerable **unperturbed** clusters in `full`, but `full` = 1 500+ cases incl. ≈ 150 unanswerable, perturbations and attacks, and several questions per §; 700–900 answerable clusters is more likely → 230–300 per block → MDE 0.062–0.067 (judged), per tenant ≈ 2.0–2.3δ. (c) "≤ 600 cases" and "three blocks of the remaining" conflict once `full` > ≈ 1 500 (1 800 → 550 + 150 = 700). | Published power claims are too optimistic; a growing `full` breaks the nightly cap silently. | Fix the row to ≈ 0.056–0.058 (≈ 1.15δ). Make the block count derived: `n_blocks = ceil((|full| − |refusal|) / (600 − |refusal|))`, recorded in the manifest (AI12-01); state the coverage period as `n_blocks` nights. Mark block cluster counts **verify** from T4.7b `stats.json`; T6.3 `mde.csv` already has a row per block. |
| AI12-06 | minor | `prompts/T3.5-retriever.md:48-52`; `docs/spec/SPEC.md:1322,1334` (M1, M13); `prompts/T7.1b-mutations-extended.md:32-34` | Y4.2 cut reranking to the top **10** with `top_k` 8, passages truncated to 256 tokens. Set-based metrics (`context_recall@8`) can then change only through fused ranks 9–10, so M1 "remove reranker" has a small recall effect and M13 "`top_n` → 2" (pre-registered "Recall on multi-hop/comparison") is ≈ 0 by construction; only rank-sensitive `ndcg_at_k` moves. Per-§ chunks are often > 256 tokens, so the reranker scores only each §'s head. T7.1b still says "T3.5's default is `top_n = 20`". | RQ3 counts designed misses as gate failures; the reranker's quality contribution (and the M1 result) is understated. | Before T7.1b freezes PREREGISTRATION: pilot M1/M13 on `core` with the pinned stack (T6.3 timing run) and retarget their expected metric to `ndcg_at_k` (or drop M13 with a decision line); or rerank top 20 for `smoke`/`core` only (their 350 queries are pipelined with GPU0) and keep 10 for `robust_pr`. Truncate passages to 384 tokens where the lane allows (T3.1b measures both). Fix the T7.1b `top_n` sentence. |
| AI12-07 | minor | `prompts/T3.5-retriever.md:52,53-56`; `docs/spec/SPEC.md:770-774`; `docs/architecture/interfaces.md:100-105` | The D222 "reranker off for `robust_pr`" mechanism is defined twice and inconsistently: SPEC = "executor override for that split only, recorded in `run.json`"; T3.5 = a candidate config value `rerank.robust_pr: off`. `/v1/retrieve` cannot know the split (random `request_id`, the target must not recognise test cases), and T3.5 also requires `/v1/retrieve` to return "exactly the order `/v1/query` would return". A third-party target has no such switch. | Either the rule cannot be implemented as written, or `/v1/retrieve` silently differs from `/v1/query` for every caller. | Add an optional request field `RetrieveRequest.rerank: bool \| None = None` (API v1, backward compatible; `None` = as configured) to interfaces §1.1/§2 and the OpenAPI schema; the runner sends `rerank=false` for `robust_pr` only when the T3.1b decision is recorded; `RunManifest.counts["retrieve_rerank_off"]`; third-party targets that ignore it are reported as "configured reranking". Remove `rerank.robust_pr` from T3.5. |
| AI12-08 | minor | `docs/engineering/gpu-cluster.md:110,169-171,194,199-201`; `prompts/T6.2a-gate-executor.md:220-226`; `docs/spec/SPEC.md:1324,1302` (M3, RQ1 e5) | GPU0 embedding residency is unplanned: (a) `bge-m3` runs with `num_ctx` 8192 under `OLLAMA_NUM_PARALLEL=4`; if Ollama sizes KV/compute for 32 k tokens for the encoder (≈ 96 KiB/token → ≈ 3 GiB + a large non-causal compute buffer, **verify**), GPU0 goes from ≈ 37 to ≈ 41+ GiB with mixed GB/GiB in the table; (b) a PR, M3 or an RQ1 config that selects another catalogue embedding model (e5-large) has no preload/unload rule (T6.2a defines one only for the generator): with `OLLAMA_MAX_LOADED_MODELS=2` the third model can evict the generator, and its first `/api/embed` during re-index/run has `load_duration` > 1 s → `model_reload` → `aborted` + retry → `error`. | M3 (pre-registered PR-tier mutation) and embedding-changing PRs can never be gated; or the generator is reloaded/offloaded mid-run. | `models.yaml` embed entries: `num_ctx` = max chunk tokens (e.g. 1024–2048, recorded with the truncation count), per-model `num_parallel` note; T3.1a S8 measures `bge-m3` VRAM at the pinned `num_ctx`. T6.2a: "a different catalogue embedding model → unload `bge-m3`, preload the PR's embed model with catalogue options before indexing; restore in `finally`" (same as the generator swap), and the VRAM table gets the e5-large row. |
| AI12-09 | minor | `docs/engineering/gpu-cluster.md:165-166,196,200-201`; `prompts/T3.1b-model-benchmark.md:44-47`; `docs/spec/SPEC.md:842` (nightly judge row) | Fallback "judge `num_ctx` 8192 if Gemma's sliding window is not sized": the generator's prompt may hold up to 8192 − `num_predict` tokens of chunks, so a faithfulness judge input (rubric + question + answer + the same chunks) regularly exceeds the 8192 − 1 024 = 7 168 cap → > 5 % `judge_truncated` → every nightly's faithfulness informational. The general rule "lower `num_ctx` before lowering `OLLAMA_NUM_PARALLEL`" is the wrong order for judges. Without SWA, `num_ctx` 12 288 × 4 ≈ 23 GiB KV + ≈ 16 GiB weights ≈ 41 GiB fits (**verify**). | Nightly judged gating silently degrades if the SWA check fails. | Rule for judges: `num_ctx` ≥ generator `num_ctx` + 2 048 (12 288 today); if that does not fit at 4 slots, lower `OLLAMA_NUM_PARALLEL` on `ollama-gpu1` to 2 before lowering `num_ctx`, and re-run the nightly budget. Update gpu-cluster §2.1/§3, SPEC §6.3 row, T3.1b. |
| AI12-10 | minor | `prompts/T6.3-noise-thresholds.md:119-120,132`; `prompts/T6.2b-gate-workflows.md:110` (`cause-switches`, `judge-drift`) | The weekly cause-switches run in the Sunday **night** mode (GPU1 = gemma), but T6.3 says baseline and switch runs use the PR judge, whose `core` baselines carry the mistral fingerprint; no mode step is defined. Same for `judge-drift` of the PR judge at night. The five targets are deterministic except the refusal row (`refusal_judged` on ambiguous answers). | Cause-switch runs either hit `no_baseline` (gemma fingerprint) or need an unplanned GPU1 swap inside the window; ≈ 5 × 900 needless judge calls. | Cause-switch runs use `judge_mode=skipped` for the four deterministic targets; the refusal row runs baseline and switch **in the same job with the night judge** (fresh baseline run on the refusal stratum, not from the store). `judge-drift` for the PR judge runs at the end of the night after `switch-mode.sh day`. State both in T6.2b/T6.3 and the budget. |
| AI12-11 | minor | `docs/spec/SPEC.md:1279-1284`; `prompts/T7.2-rq3-gate-benchmark.md:11,94-96`; `prompts/T7.3-rq1-grid.md:80`; `prompts/T7.4-make-experiments.md:34`; `docs/decisions.md` D230 | SPEC §8 says experiments run "only in `MAINTENANCE` windows (weekends)", but D230 makes `MAINTENANCE` datagen-only and T7.2/T7.3/T7.4 say "never while `MAINTENANCE` exists". GPU-hour figures disagree: SPEC ≈ 65 runs ≈ 55–75 h, T7.2 52 runs ≈ 25–45 h. | Agents get contradictory scheduling rules; the calendar is sized on the wrong number. | SPEC §8: "experiments run in day mode under `gpu.lock`, weekday gaps and weekends, never while `MAINTENANCE` exists or in the night window"; one figure from `budget.py --experiment` (52 runs × 55–75 min ≈ 48–65 GPU-h on this estimate). |
| AI12-12 | minor | `prompts/T6.2b-gate-workflows.md:110,166-170` (`nightly-failed` issue); `docs/spec/SPEC.md:1111-1116` (no-op bounds) | Two gated comparisons per night (block gate + drift), each accepted at a no-op `fail` rate ≤ 0.03, and `executor-health` opens `nightly-failed` on any failure: up to ≈ 6 %/night ≈ 35 %/week of false issues at the bound (lower at the realised rate, **verify** in T6.3 replay). | Alarm fatigue on the one signal meant to catch cumulative drift. | T6.3 replay reports the per-night and per-week false `nightly-failed` rate; `check_heartbeat.py` opens the issue on a hard fail / absolute fail immediately, but on a statistical `fail` only when the same metric fails on two consecutive nights (or on the drift job twice). |

Counts: **0 blocker, 3 major, 9 minor** (12 findings).

## Judge model plan on this hardware

### VRAM per card and mode (planning; f16 KV, flash attention; GiB)

| Server / mode | Weights | KV (`num_ctx` × 4) | Other | Card total of ≈ 45 GiB | Verdict |
| --- | --- | --- | --- | --- | --- |
| GPU0 day/night: `qwen3.8:27b-q8_0` + `bge-m3` | 27 + 1.1 | 8192 × 4 × 256 KiB = 8 (arch **verify**) | `bge-m3` ctx 0–3 (**verify**, AI12-08), compute 1–2 | 37–41 | fits; no room for a third model or 16 k |
| GPU1 day: Mistral Small 24B `Q4_K_M` | 13.4 (+ ≈ 0.8 vision tower) | 16384 × 4 × 160 KiB = 10 | compute ≈ 1 | ≈ 25 | fits |
| GPU1 night: Gemma 3 27B `Q4_K_M`, SWA sized | 15.6 (+ ≈ 0.8 vision) | ≈ 6–8 | ≈ 1 | ≈ 24–26 | fits |
| GPU1 night: Gemma 3 27B, **no** SWA | 15.6 | 16384: 31; **12288: 23**; 8192: 15.5 | ≈ 1.5 | 48 / **≈ 41** / 33 | use 12 288 (AI12-09), not 8 192 |
| `ollama-all` datagen: Llama 3.3 70B `Q4_K_M` | ≈ 40 (20/card) | 8192 × 4 × 320 KiB = 10 (5/card) | ≈ 1/card | ≈ 26/card | fits; layer split runs one card at a time |

### Throughput vs budgets (estimate; T3.1b replaces it)

Inputs: generator prompt ≈ 5 k tokens (8 §-chunks), answer ≈ 250 tokens; judge calls ≈ 900 per PR run
(faithfulness ≈ 6 k, correctness ≈ 1 k, refusal/other ≈ 0.6 k tokens in), ≈ 150 tokens out.

| Lane | PR tier (smoke 50 + core 300 generated, `robust_pr` 300–440 retrieve-only) | Nightly (refusal stratum + one block, ≤ 600) |
| --- | --- | --- |
| GPU0 generator | 350 gens: prefill 1.75 M tok ≈ 22–32 min + decode 88 k tok ≈ 24–32 min → **46–64 min** | 600 gens → **80–112 min** |
| GPU1 judge | mistral ≈ 2.0 M tok prefill ≈ 21–31 min + 135 k decode ≈ 20–28 min → 41–59 min, pipelined → tail + 5–10 min | gemma ≈ 1 800 calls, ≈ 3.3 M tok ≈ 42–61 min + 270 k decode ≈ 50–75 min → **92–136 min**, overlapped |
| VM CPU rerank (10 × 256) | 650–790 queries × 1.5–5 s ≈ 16–66 min; without `robust_pr` 9–29 min (pipelined) | 600 × 1.5–5 s ≈ 15–50 min (pipelined) |
| Mode switches / loads | none in day mode (models resident) | day→night→day: 2 GPU1 loads ≈ 4–5 min at 1 GbE; + 2 if the PR judge is needed at night (AI12-10) |
| Verdict | **≈ 55–75 min**: fits 90 min, most likely with `robust_pr` rerank off or ONNX int8 (D222 fallback); margin shrinks with long Qwen answers and with coding agents loading the same 8 vCPUs | **≈ 2–2.5 h**: fits 8 h easily; Sunday + 5 cause-switch `core` runs (≈ 4–5 h) ≈ 7 h (tight, the D223 "replace block" rule may fire); a release run of all of `full` (≈ 5–7 h) fits only alone in a night window |

The 150-case judged-subset fallback (D199) is unlikely to be needed on these numbers; the binding risks are
the CPU rerank lane (handled by D222) and unplanned reloads (AI12-08), not GPU time.

### Native Ollama options, determinism, NAS

- Native `/api/chat` + `/api/embed` with catalogue `num_ctx` (D219/D220) is correct; the remaining gap is that
  the proxy also freezes per-request sampling options (AI12-02). Preload must carry the same `options`
  (AI12-04).
- Determinism: `temperature 0` + `seed` with 4 parallel slots is not batch-invariant; correctly absorbed by the
  target/judge caches and σ_d(churn), except in the local drift rule (AI12-03) and in the noise study once
  AI12-02 is fixed. Publish the T5.4 self-agreement next to κ.
- NAS: first load per mode excluded from budgets (fine); every reload inside a run aborts it (D245
  `model_reload`), so the reload sources that remain are embedding swaps (AI12-08) and judge swaps at night
  (AI12-10). T0.6 C6 should also time a second read of the same blob (cluster page cache) because night↔day
  swaps re-read the same 15–17 GB files daily.

## Eval method and calibration

- Judge prompts (German, reason before score, nonce-wrapped blocks, `format` JSON schema, `reason` ≤ 600
  chars, `num_predict` 384), family separation, the D224 fallback rule and the AI11-11 `legal_hard`
  validity filters are sound and consistently applied.
- Pass rule (κ ≥ 0.6 on the full set, hard-negative specificity ≥ 0.80 with Wilson LB ≥ 0.70, discrimination
  ≥ 0.90): at n ≥ 150 hard negatives the Wilson clause is non-binding (p̂ = 0.80 → LB ≈ 0.73); fine.
- Drift: hosted rule unchanged; local rule needs the two-sample form (AI12-03).

## Statistics with the real split sizes

| Gated pair | Applicable clusters | MDE (σ_d planning, m ≈ 40) | Note |
| --- | --- | --- | --- |
| `core` overall, judged/retrieval | 200–220 | 0.069–0.072 (≈ 1.4δ) | arithmetic in SPEC correct |
| `core` per tenant | 60–70 | 0.12–0.13 (≈ 2.5δ) | correct |
| `robust_pr` `perturbed_all` | 40 | 0.10–0.16 | first-stage only if D222 fires |
| nightly block, judged (δ 0.05) | 230–330 (**verify**, AI12-05b) | 0.062–0.067 | SPEC assumes 330 |
| nightly block per tenant | 75–110 | 0.10–0.12 (≈ 2.0–2.3δ) | |
| nightly `false_refusal` (δ 0.03, σ 0.17) | 230–330 | 0.038–0.040 | |
| nightly `refusal_correct` (δ 0.10, σ 0.30) | ≥ 100 | 0.125 | correct; same stratum every night, so consecutive nights are not independent tests |
| release `full`, judged | 700–1 000 | **0.057–0.058** (SPEC says 0.050–0.054, AI12-05a) | |
| `injection_success` (Wilson, n = 30) | 30 | FAIL at k ≥ 3, WARN at k = 2 | unchanged |

Nightly rotation power: each night tests one third of `full`; a regression is seen by the block nights in
turn, never pooled. A weekly pooled test over the three newest block runs (AI12-01, optional) recovers the
release-level MDE ≈ 0.057 once a week.

## RAG design

Hybrid dense (`bge-m3`) + own German sparse vectors, tenant filter inside every prefetch, RRF, explicit
prompt budget (`num_ctx − num_predict`), `used_in_prompt`, `/v1/retrieve` for `robust_pr`: sound. Weak points
are all on the reranker after the Y4.2 cut: positions 9–10 only for set metrics and 256-token heads of long §§
(AI12-06), and the `robust_pr` reranker-off contract (AI12-07). Embedding swaps on GPU0 need the same
preload discipline as generator swaps (AI12-08).

## RQ validity

- **RQ1**: sound (evidence-span primary metric, e5 prefixes, pre-registered `answer_correctness` subsample);
  the e5 arm depends on AI12-08 if e5 is served on GPU0.
- **RQ2**: sound size contrast (Gemma 12B vs 27B), 70B arm for faithfulness only; κ should be shown with the
  judge's self-agreement ceiling.
- **RQ3**: M17 is neutralised by the proxy (AI12-02), M1/M13 expectations need re-piloting after Y4.2
  (AI12-06), M3 depends on embedding preload (AI12-08), N10 now consistent (GPU0 binary only). Scheduling text
  conflicts (AI12-11).

## Round-11 AI findings: status

Resolved, no residual: AI11-01 (D219/D220, serving evidence in SPEC §6.2), -02 (D218/D222), -03 (D222 + three-lane
`budget.py`), -04 (D223), -05 (D224), -06 (D247 exit 15), -07 (SPEC §6.3 rows, `kv_bytes_per_token`, `swa_window`;
fallback refined by AI12-09), -08 (T0.6 provenance probe, DATA_LICENSES rows 28/96), -11 (T5.3 validity
filters), -12 (SPEC §3.5/§6.3), -13 (SPEC §8 GPU-time plan; wording conflict → AI12-11), -14a/b/e. Residuals:
AI11-09 (digest in `judge_serving`: interfaces not updated) and AI11-14c/d (env vars, preload options) →
AI12-04; AI11-10 (local drift rule adopted but degenerate at `a0 ≈ 1`) → AI12-03.
