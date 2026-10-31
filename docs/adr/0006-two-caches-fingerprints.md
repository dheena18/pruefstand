# 0006 — Separate target and LLM caches keyed by fingerprints

- Status: Accepted
- Date: 2026-10-27
- Tasks: T1.8, T5.1, T6.1
- Revised: 2026-10-28 (round-1: judge key, serving in fingerprint, trust domains; round-2: namespace `llm`, `models` in the target fingerprint); 2026-10-31 (round 8: provider version in the judge key, drift anchors; round 9: judge serving + `judge_epoch` in `eval_fingerprint`, 50-anchor drift rule, static `/v1/info.serving`); round 11 (AI11-09 model digest in judge serving, AI11-10 drift rule for local judges, D224 fallback judge)

## Context
Spec v1 keyed the response cache on `hash(question, tenant, config)`. Under that key, a PR that changes
retrieval **code** but not `rag.yaml` would be served the old, good answers from the cache and would pass.
The gate would hide exactly the regression it exists to catch.

## Decision
Use two namespaces in `DiskKVCache`:

| Cache | Key | Reused when |
| --- | --- | --- |
| `target` (runner) | `stable_hash(target_fingerprint, case.id, case.question, case.tenant)`, where `target_fingerprint = stable_hash(image_digest or git_sha, config_hash, corpus_version, sorted(models.items()), serving)` (signature in `interfaces.md` §17, which wins) | the app build, config, corpus, models and serving stack (static fields only: engine, engine version, quantisation, GPU model, model file SHA-256, `cpu_model` on CPU; runtime counters live in `/v1/health` and never enter the fingerprint) are all the same |
| `llm` (`LLMClient` only; judge, datagen and perturbation calls) | `stable_hash(model, provider_version, prompt_id, prompt_version, rendered messages, temperature, max_tokens, seed, response_format)`. For a judge: model id + provider-reported version + prompt version + hash of **all rendered inputs** (question, answer, context chunk ids and text hashes, reference) | the judge (incl. its provider-reported version), the prompt and every input are the same; the same answer with different context is a cache miss |

Fingerprints are computed only in `core/fingerprint.py`. `stable_hash(*parts)` hashes the canonical JSON
of its arguments.

`eval_fingerprint` (which runs may be compared) covers dataset name + version, splits, the
**configured** judge model ids, each judge's **serving version**
(`"<engine> <engine_version> <quantization> <digest[:12]>"`; the digest closes the mutable-tag gap,
AI11-09)
and **`judge_epoch`** (integer, bumped by re-calibration), judge prompt versions, metric versions and
`corpus_version`. A judge-serving change or an epoch bump therefore forces a new baseline (`no_baseline`
→ `baseline-promote`), so baseline verdicts from one judge are never paired with candidate verdicts
from another. Run-time flags (`judge_drift`, `judge_degraded`, `judge_fallback`) never change it;
a `judge_fallback` run therefore reports every judged metric as informational and is not promoted as a
judged baseline (D224), so two judges' verdicts are never paired.

**Trust domains.** Only `main` and nightly jobs in the private executor write the shared caches. PR
jobs read the main cache and write to a PR-scoped overlay directory that is deleted after the job, so
a PR can never place a value under a key main will read.

An opaque third-party target without `/v1/info` gets a per-run fingerprint, so its responses are never
reused from the cache. The `llm` cache saves the most cost: a case whose rendered judge inputs (answer
**and** context **and** reference) did not change is never judged again. A key over the answer alone is
forbidden: it would reuse a faithfulness verdict after retrieval broke.

**Judge drift.** A judge can change behind the same id. Nightly re-judges a fixed anchor set of 50
public items with the cache bypassed (`judges/drift.py` `anchor_agreement`). Rule: drift iff ≥ `max(3, ceil(0.1 · n))` anchor verdicts changed vs the stored verdicts (n = anchors, 50 → 5), the same count rule for hosted and local judges (round 12 N3; `is_drift(..., a0=)` keeps its signature). Local Ollama judges (digest and engine pinned) also drift when the
digest/engine differs; a passing anchor re-run clears it. Hosted judges: re-calibration clears it and
bumps `judge_epoch` (SPEC §5.4, §7.5). On
drift the run records `judge_drift=true`, that judge's cache entries are invalidated, and its judged
metrics are informational until the flag clears. Drift alone does **not** change `eval_fingerprint`;
it only invalidates the judge cache.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Spec v1 key | Hides code regressions (critical) |
| No caching | Doubles the cost, and each re-run adds judge noise |
| Cache by the git tree hash of the whole repo | A docs-only change would invalidate everything |

## Consequences
- Positive: the cache cannot serve a stale answer, and repeated judgments cost nothing and come back identical.
- Negative: rag-demo must expose `/v1/info` with its image digest or git SHA and its config hash.
- Test: changing app code while keeping the same `rag.yaml` must change `target_fingerprint` (unit test in T6.1).
- Test: same answer, different `kontext` → `llm` cache miss (T5.1).
- Qwen3 `enable_thinking` is part of rag-demo's `config_hash`, so the template flag cannot change answers without changing `target_fingerprint`; `/v1/info.serving` includes `cpu_model` and the llama.cpp build as `engine_version` on CPU profiles; `<think>` strip counts and `truncated_chunks` are in `/v1/health`.
- Test: `eval_fingerprint` is identical with and without `judge_drift` / `judge_fallback`, and changes when a judge's serving version (incl. the model digest) or `judge_epoch` changes (T1.1).
- `robust_pr` target-cache entries hold `/v1/retrieve` responses (no answer; D218/D222); the key is unchanged.
