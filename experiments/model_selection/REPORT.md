# T3.1b model benchmark: report (phase 1, resident set only)

Status: **partial** (phase 1 only; T3.1b Done-when items for candidates, embeddings, rerankers and pins are open). Run on 2026-11-03 against the models already resident (generator `qwen3.8:27b-q8_0`,
`bge-m3`, judge `gemma3:12b`; Ollama 0.32.13, `OLLAMA_NUM_PARALLEL=4`, KV `q8_0`), under `pruefstand-lock`, no gate
running (executor service inactive, no containers, lock acquired at once). No model was pulled, removed or swapped.
Raw numbers: `results/2026-11-03.csv` (column `run_id`: r1 = throughput, parallel, json, vram at 01:04; r2 = kv, longctx at 01:13; r3 = quality rerun with corrected scoring; reloads of r3 derived from the answers file), answers: `results/2026-11-03_answers.jsonl`. Paths are redacted.
Reproduce: `make bench-models` (phases via `BENCH_PHASES=`), budgets: `PYTHONPATH=experiments python -m model_selection.budget`.

## Done in phase 1

| Item | Result |
| --- | --- |
| Generator licence/digest | `ollama show`: Apache licence, family `qwen35` 27.3 B `Q8_0`, digest still `8f5fb6b7...1766039` (probe of 2026-11-02 and `health.sh`) |
| German smoke (107 items, deterministic 0-2 score) | generator mean 1.83 (95 % CI 1.72-1.93); judge model 1.67 (1.53-1.81). CIs overlap; roles differ, so no pick between them |
| `<think>` in answers | 0 of 214 |
| Judge JSON (50 calls, schema, `num_predict` 384) | validity 50/50 (1.00), verdict accuracy 0.96. Without `format` the judge model wraps JSON in code fences (quality item kind `json`: 0.0), so the schema is required |
| Throughput generator (about 2 570 prompt tokens, about 140 out) | c=1: 19.4 tok/s, prefill 967 tok/s, TTFT 2.7 s; c=4: aggregate 14.5 tok/s, TTFT p50 30 s; c=8: aggregate 14.4 tok/s, TTFT p50 66 s. **It does not batch** (serialises requests) |
| Throughput judge (about 2 720 prompt tokens, about 150 out) | c=1: decode 56.9 tok/s per stream (36.3 aggregate incl. prefill), prefill 1 625 tok/s, TTFT 1.8 s; c=4: decode 25.6 per stream, 54.5 aggregate, TTFT p50 4.3 s; c=8: 57.2 aggregate, TTFT p50 12.4 s. Per-stream decode excludes prefill, aggregate includes it |
| Generator and judge at the same time (4 streams each) | no interference: generator 14.5 tok/s aggregate, judge 55.3 tok/s aggregate |
| Reloads (`load_duration` > 1 s) | generator 0 in every phase; judge 4 in the quality run (the first 4 concurrent calls of the run shared one 8.3 s load; models were resident, so this was a re-load, cause not identified); 0 in throughput, parallel and json. The `kv` and `longctx` phases reload on purpose. The committed `longctx` rows come from the first version of the phase, which alternated 12 288 and 16 384 per call (about 40 uncounted reloads, judge left at 16 384 until `make gpu-health`/next call restored it); token counts and verdicts stay valid, the code now runs all pinned calls first, counts reloads and restores the catalogue context. First-load times from the cluster disk were not taken (models were resident) |
| VRAM per card | GPU0 28 137 MiB, GPU1 13 392 MiB used (of 46 068); `bge-m3` 0.63 GB at `num_ctx` 1 024 (`/api/ps`); judge 10.2 GB at 12 288 x 4 |
| Judge context 12 288 | fits with room; 20 inputs of 9 146-9 220 tokens: `prompt_eval_count` equal at 12 288 and 16 384, 20/20 equal verdicts; allowance max 139 tokens (rule: <= 3 072). `OLLAMA_NUM_PARALLEL` stays 4 |
| KV per token (`/api/ps` slope) | **unreliable**: judge 7.9 KB per token at 4 slots (sliding window active); generator 11.9 KB if 4 slots, 47.6 KB if it really ran 1 slot (it behaves like one). `/api/ps` sizes are estimates and not monotonic for the judge. `models.yaml` `kv_bytes_per_token` stays unpinned (D472); the load log is needed |

## Budgets (D471; `budget.py report`)

| Run | GPU0 | GPU1 | CPU rerank | Binds | Limit |
| --- | --- | --- | --- | --- | --- |
| PR, full core (350 generations, 900 judge calls, 790 queries) | 81.9 min | 49.7 min | 15.8 min (1.2 s/query, **assumed**) | GPU0 | 90 min: fits, 8 min margin |
| PR, 150-case judged subset | 56.4 min | 24.8 min | 15.8 min | GPU0 | fits |
| Nightly (600 generations, 1 800 judge calls) | 139.3 min | 99.3 min | - | GPU0 | 480 min: fits |

Inputs: generator `slots=1`, 19.4 tok/s, prefill 966 tok/s, 3 500 prompt / 200 output tokens; judge 4 slots, 25.6 tok/s per
stream, prefill 1 625 tok/s, 3 000 / 150. Remedy order if GPU0 grows: pin `generation.max_tokens` and the prompt budget in
`rag.gpu.yaml` before the first baseline, then the 150-case subset. Weekly cause-switch estimate: one `core` run per switch,
about 82 min each (not summed into the nightly).

## Server parallelism check

Read-only, via the wrapper status: the server environment `matches cluster.env`, whose template sets `OLLAMA_NUM_PARALLEL=4`.
So the server is configured for 4 slots, yet the generator showed no batching. The effective slot count per model is not
visible there; the Ollama load log would show it (and fix `kv_bytes_per_token`). Follow-up: wrapper op to read the load log.

## Budget caveats

- The generator lane assumes 200 output tokens, but `num_predict` is 512. With 512 output tokens the PR GPU0 lane is about 175 min,
  not 82. Remedy (a) (pin `generation.max_tokens` and the prompt budget in `rag.gpu.yaml`) must be done before the first baseline.
- The judge prompt in the benchmark is shorter than a real generator context; real judge lanes may be longer.
- Latency under queueing: generator TTFT p95 32 s at 4 streams and 70 s at 8 streams (it serialises). Client timeouts in T3.6 and
  gate timeouts in T6.2a must allow this.
- The CPU rerank lane (1.2 s per query) is an assumption, not a measurement.

## Not done (needs a swap, a stack or the owner)

| Item | Needs |
| --- | --- |
| Second generator candidate: `qwen3:4b` Q4_K_M (2.5 GB, in catalogue) | pull (free disk now about 4.5 GB, reserve 2 GB: fits only barely) |
| Second judge candidate (e.g. `gemma3:4b`, about 3.3 GB) | pull plus catalogue entry; swap rule, one at a time |
| Embeddings `jeffh/intfloat-multilingual-e5-large-instruct:f16` (1.1 GB), one German model | pull; GermanDPR/GerDaLIR download [NET]; `indomain_dev.jsonl`: tooling, rules and the 240-passage plan are done; the questions need GitHub Models (section below) |
| bge-m3 cosine >= 0.99 vs HF checkpoint (20 passages) | HF download [NET] on the VM CPU |
| Rerankers (`bge-reranker-v2-m3`, `gte-multilingual-reranker-base`), CPU latency, 384-token variant | compose stack with `rerank-cpu` (`stack.lock`) and HF download; `embed_bench.py` has the helpers |
| Scoring of S3 by the GitHub Models datagen model and by a person on 10 items | datagen model (T4.2) not pinned; HUMAN |
| `provisional: false` pins in `models.yaml` | only after the above (pin check: `pins.py`, `require_final=True`) |

Note: contexts in `questions_de.jsonl` are shortened statute wording written for the test; the deterministic score is a proxy,
not a quality verdict.

## Owner scoring of 10 items (HUMAN)

`owner_score_10.csv` holds 10 generator answers from the committed run (`results/2026-11-03_answers.jsonl`),
picked with a fixed seed, round-robin over the 7 kinds so each category appears at least once. Rebuild with
`PYTHONPATH=experiments python -m model_selection.owner_sheet --answers experiments/model_selection/results/2026-11-03_answers.jsonl`
(the committed file is checked by `test_candidate.py`). Fill the empty `score` column with 0, 1 or 2, using the same meaning as the
deterministic scorer (`bench_cases.score_case`); read `context` (the passage the answer must rest on) next to `question`:

| Score | Meaning |
| --- | --- |
| 2 | German, no `<think>`, correct and complete for the question (and, where a context is given, supported by it); for refusal items it says the documents do not contain the answer; for register items it uses "du" for a du-question |
| 1 | at least half right: the core fact is there but incomplete, partly wrong, or the wrong register |
| 0 | empty, wrong, English, hallucinated beyond the context, a refusal where the context answers, or an answer where a refusal was required |

Commit the filled file; the mean of the ten human scores is compared with the deterministic score of the same items.
The owner-actions list of the PR repeats this.

## Candidate pass (`make bench-models CANDIDATE=<catalogue tag>`)

One candidate at a time, after the lead has pulled and loaded it by the swap rule (`MAINTENANCE`, one model, at least 2 GB free on the
cluster disk, ADR-0019). The pass runs under `pruefstand-lock`, only for a tag listed in `infra/gpu/models.yaml` with role `generator`
or `judge` (embeddings: `embed_bench.py`), refuses to start when the tag is not pulled, and never pulls, removes or swaps. It
appends to `results/<date>.csv` (phases `cand_load`, `cand_quality`, `cand_json`, `cand_throughput`, `cand_vram`; column `run_id`
starts with `cand-`) and writes the answers to `results/<date>_<tag>_answers.jsonl`.

| Step | Metric (CSV `metric`) |
| --- | --- |
| first call, before anything else | `first_load_s` (cold load from the cluster disk when `was_resident` is 0) |
| German smoke, 107 items | `score_mean`, `ci_lo`, `ci_hi`, `think_answers`, `reloads` |
| judge JSON, 50 calls with the schema | `json_validity`, `verdict_accuracy` |
| throughput, concurrency 1 and 4 | `decode_tps_per_stream`, `decode_tps_aggregate`, `prefill_tps`, `ttft_p50_s`, `ttft_p95_s`, `reloads` |
| VRAM | wrapper `status` per card (`gpuN_used_mib`, `_delta` to before the load), `/api/ps` `size_vram_gib`, `disk_gib`, `overhead_gib`, `disk_free_gib` |

**`overhead_gib` (provisional).** Estimated as `size_vram` (`/api/ps`) minus the model's `disk_bytes` (catalogue), in GiB. It still includes the KV cache at
the pinned `num_ctx` and slots, so it is an upper bound of the vision tower plus compute buffer that `fits()` needs
(`budget.py`); the Ollama load log gives the exact split and replaces it. A negative value means partial CPU offload. The day-set
models get the same figure from `make bench-models BENCH_PHASES=overhead` (phase `overhead`, resident models only).

The lead unloads first (`make gpu-down`): the pass refuses with "no room" while more than two other models are resident, loads the candidate explicitly with the catalogue options, and fails when that load evicted a model that was resident before or when `/api/ps` has no entry for it.

### Candidate comparison (the lead fills one row per pass)

Reference rows are the committed phase-1 numbers; `n/m` = not measured yet. Pick by the rule of S3: German quality first (CIs must not
overlap), then JSON validity, tok/s, VRAM headroom; the lead decides swaps.

| Model (role) | run_id | Smoke mean (95 % CI) | JSON validity | Decode tok/s c=1 | Aggregate c=4 | TTFT p50 c=4 | First load (s) | size_vram / disk (GiB) | overhead_gib (prov.) | Reloads | `<think>` | Pick |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen3.8:27b-q8_0` (generator, resident) | r1, r3 | 1.83 (1.72-1.93) | n/a | 19.4 | 14.5 | 30 s | n/m | n/m / 27.9 | n/m (phase `overhead`) | 0 | 0 | reference |
| `gemma3:12b` (judge, resident) | r1, r3 | 1.67 (1.53-1.81) | 1.00 | 56.9 | 54.5 | 4.3 s | n/m | n/m / 7.6 | n/m (phase `overhead`) | 4 | 0 | reference |
| `qwen3:4b` (generator candidate) | cand-2026-11-03T1126 | **0.00** (0.00-0.00); all 107 answers English with visible reasoning although `think: false` | 1.00 (accuracy 0.98) | 132.5 | 218.4 | 2.0 s | 11.6 (cold) | 4.90 / 2.33 | 2.58 | 0 | 0 | not a candidate |
| second judge candidate (needs a catalogue entry first) | | | | | | | | | | | | |

## In-domain dev set `indomain_dev.jsonl` (S4 primary ranking set): status

Tooling, rules and tests are in (`indomain_data.py`, `indomain_gen.py`, `indomain_cli.py`, prompts `indomain_gen_v1` and
`indomain_check_v1`, card `indomain_dev_card.md`). The 240 planned passages (200 items plus 40 reserve, seed 20261103, 19 public laws,
T1.13 slice norms excluded) are committed in `indomain_dev_sources.json` as the T4.x exclusion list (`source_passage_ids`).
**The questions are not generated yet:** GitHub Models answers `200 text/plain OK` to every path from the VM and from the cloud
sandbox, so no generation call succeeds there. Run the steps where `models.github.ai` answers JSON (the owner's laptop with the
`PRUEFSTAND_GH_MODELS_TOKEN` PAT, or an Actions job with `models: read`):

```bash
python data/download.py $(python -c "import sys; sys.path.insert(0,'experiments'); from model_selection import indomain_cli as c; print(' '.join('--only '+i for i in c.source_ids()))")
PYTHONPATH=experiments python -m model_selection.indomain_cli generate --max-calls 120 --env-file .env   # repeat daily until 240 are cached
PYTHONPATH=experiments python -m model_selection.indomain_cli check --max-calls 40 --env-file .env       # second family, first 30 items
PYTHONPATH=experiments python -m model_selection.indomain_cli assemble
```

A 429 ends a step cleanly (exit code 3); every answer is cached under `data/raw/indomain_dev_cache`, so reruns cost no quota.
`assemble` writes `indomain_dev.jsonl`, `indomain_dev_checks.jsonl`, the final sources list and the card.

## PR time budget with a 20 % margin (D655, owner rule 2026-11-03)

A PR run must stay below **72 min** (90 min budget, 20 % margin); anything above 72 min **does not fit**. The generator
`qwen3.8:27b-q8_0` serves one sequence (Ollama: `model architecture does not currently support parallel requests`, D654), so the
generator lane is single-slot at about 19.4 tok/s per stream. Inputs measured 2026-11-03: prompt about 1 650 tokens (prefill
966 tok/s), embedding 0.19 s per query, rerank 0.5 s per query (**assumed**; 0.18 s was measured for two short passages after the
thread fix, D650); `max_tokens` stays at **256**. Computed by `budget.py` `scenarios()`:

| `max_tokens` | PR full core (350 generations) | margin | PR 150-case subset (240 generations) | margin | verdict |
| --- | --- | --- | --- | --- | --- |
| 150 | 57.6 min | 36 % | 40.3 min | 55 % | both fit |
| 200 | 72.6 min | 19 % | 50.6 min | 44 % | full core does not fit (just over 72), subset fits |
| **256 (the cap)** | **89.4 min** | **0.7 %** | **62.1 min** | **31 %** | **full core does not fit, subset fits** |
| 512 | 166.4 min | negative | 114.9 min | negative | nothing fits: never raise the cap |

**Decision (D655).** PR runs use the 150-case judged subset by default (D199): 62.1 min at the 256 cap, margin 31 % (27.9 min).
The full `core` set runs in the nightly (night window 22:00 to 06:00, at most 8 h = 480 min): 600 generations take 149 min at
256 tokens, margin 69 % (331 min); at 200 tokens 120 min (75 %). The first real tier-2 runs measure the mean output length; the
table is recomputed then (it is the only open input besides the assumed rerank time).

## Open option: a parallel-capable generator (not started, decision for the owner)

The `qwen35` generator cannot batch, which is why the full core set does not fit a PR run. A dense generator that supports
parallel slots (Qwen3-14B `q8_0`, about 16 GB, or Qwen3-32B `Q4_K_M`, about 20 GB; sizes are the planning values of
`gpu-cluster.md` section 3, to be confirmed from the registry when a catalogue entry is added) could serve 4 slots. A candidate
pass (quality, tok/s at 1 and 4 slots, VRAM, PR time with the full set) needs the model on the cluster disk. It does **not fit**
without removing the judge or the embedding model, and the generator is never removed (D451): the models disk has **2.20 GiB
free** (reserve 2 GiB, so 0.2 GiB of headroom). If every removable catalogue model went (`qwen3:4b` 2.33, `gemma3:12b` 7.6,
`bge-m3` 1.08 GiB), at most **11.2 GiB** would be usable for a candidate, less than either model. No swap was done and none is
planned. Choices for the owner: (a) keep the generator and the judged subset (current), (b) free cluster disk (or add a disk) and
run the candidate pass, (c) wait for Ollama to support parallel requests for this architecture.

