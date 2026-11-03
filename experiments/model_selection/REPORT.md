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
| Embeddings `jeffh/intfloat-multilingual-e5-large-instruct:f16` (1.1 GB), one German model | pull; GermanDPR/GerDaLIR download [NET]; `indomain_dev.jsonl` (200 hand-written questions) is not written |
| bge-m3 cosine >= 0.99 vs HF checkpoint (20 passages) | HF download [NET] on the VM CPU |
| Rerankers (`bge-reranker-v2-m3`, `gte-multilingual-reranker-base`), CPU latency, 384-token variant | compose stack with `rerank-cpu` (`stack.lock`) and HF download; `embed_bench.py` has the helpers |
| Scoring of S3 by the GitHub Models datagen model and by a person on 10 items | datagen model (T4.2) not pinned; HUMAN |
| `provisional: false` pins in `models.yaml` | only after the above (pin check: `pins.py`, `require_final=True`) |

Note: contexts in `questions_de.jsonl` are shortened statute wording written for the test; the deterministic score is a proxy,
not a quality verdict.
