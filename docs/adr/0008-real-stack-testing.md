# 0008 — Real-stack testing: real models, real target, real CI

- Status: Accepted (2026-10-28, replaces the earlier test-double design; owner decision; revised 2026-10-31, round 8 W1; round 9 X1.4, X3.11, X3.15, X5.6)
- Date: 2026-10-28
- Tasks: T1.3, T1.4, T1.11, T1.12, T1.13, T6.3

## Context
The owner requires that every test touching models or the RAG app uses **real** LLMs, real
embeddings, a real vector store and the real app, in real GitHub CI. Test doubles for models or the
target produce results that cannot be trusted as evidence ("just a draft"). The gate still needs
proof that known bugs FAIL and no-ops PASS, and CI must stay free (public repo, free model tiers).

## Decision
1. **No fake LLM backends and no fake targets** in the package or the tests.
2. **Tier 1 live CI** (`live-e2e.yml`, GitHub-hosted CPU runner) runs the whole product on every
   same-repo PR, on `main` and nightly: real Qdrant, real rag-demo, real llama.cpp generator (≤ 2B
   params, GGUF Q4_K_M, family `qwen`, thinking disabled), real CPU embeddings, no reranker, real 5-law
   slice corpus, on the 20-case `smoke_live` split (`top_k: 4`, chunk text ≤ 256 tokens in the prompt,
   `max_tokens: 256`; ≤ 20 min, `timeout-minutes: 30`). The **tier-1 gate decides on hard fails and
   `error_rate` only**; `injection_success` (2 injection cases), language, citation and refusal-phrase
   results are **reported, never deciding** (injection is gated in tier 2 on ≥ 30 injection cases);
   paired statistics are `INSUFFICIENT_DATA` at n = 20. The baseline is the `live-baseline` artefact,
   written only by push-to-`main` runs of the 20-case PR shape (nightly 40-case runs write
   `live-baseline-nightly`, never compared by PRs). Judged metrics are **informational**: ≤ 10 judge
   calls per PR through **GitHub Models** with `GITHUB_TOKEN` (`permissions: models: read`, free tier),
   cached. No uncalibrated judge ever decides a required check.
3. **FAIL paths are proven with real bug switches** in rag-demo's profiles (`configs/rag.yaml` for
   tier 1, `configs/rag.gpu.yaml` for tier 2)
   (`tenant_filter: inside | post_topk`, `shared_public_merge: filtered | unfiltered`,
   `reranker: on | off`, `injection_guard: on | off`, `system_prompt_guard: on | off`, `top_k`, prompt variants without citation/refusal instructions (`answer_<variant>_de_v1.txt`),
   `answer_language: auto | en`). These are real code paths, shared with the mutation benchmark (SPEC §8).
   The tier-1 scenario matrix runs nightly and on PRs touching `apps/rag-demo/**`, one parallel job per
   scenario (≤ 20 min each), and asserts only deterministic outcomes (hard fail / absolute check), so it
   is not flaky. Tier-1 scenarios: `tenant_filter`, `shared_public_merge`, `system_prompt_guard`,
   `injection_guard` (marker count reported, not gating) and a whitespace no-op. Scenarios that need
   statistics (`answer_language: en`, `reranker: off`, `top_k`, prompts without citation or refusal
   clause) run in tier 2 and in the MVP demos (T6.5); retrieval-only scenarios use `POST /v1/retrieve`
   (no generation; D218), and the tier-2 `cause-switches` run weekly, not nightly (D223).
4. What stays below the live line:
   - pure-function unit tests on **real inputs** (real § text, real questions, real configs);
   - **statistical validation** of `gate.stats`/`gate.policy` on simulated numbers, because the true Δ
     must be known to measure type-I error and power (this tests maths, not the product);
   - **cassettes**: replays of responses recorded from real model calls (`make cassettes`, re-recorded
     weekly by `cassettes.yml`), only for fast parser/retry/cost/plumbing tests of code that calls a real model or the real target
     (scope list in `CLAUDE.md` §6). Every
     behaviour a cassette covers is also covered by a live test.
5. Fork PRs get no `models` permission: tier 1 then runs deterministic metrics only, records
   `judge_mode=skipped` and says so in the comment. There is no CPU fallback judge.
6. GitHub Models budget: ≤ 10 calls per PR, ≤ 60 calls per nightly (canary-bearing cases excluded before counting); the real daily limit is measured by a
   24-hour probe in T0.6 (`ci-cd.md`). Judgments are cached by the judge cache key of ADR-0006 (model
   id + provider-reported version + prompt version + hash of all rendered inputs). When the quota is
   exhausted the judged cases are skipped (`judge_mode=skipped`); the required check is unaffected.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Deterministic fake LLM + fake target with injected degradations | Rejected by the owner: results are not evidence about real behaviour |
| Only the A40 tier runs models | Cluster outages would leave PRs with no real signal; forks would get nothing |
| Paid hosted judges in CI | Free-only rule (ADR-0009) |

## Consequences
- Positive: every PR gets real numbers and a real PR comment from the real system; the walking
  skeleton (M1) is real end to end; bug switches double as mutation-benchmark entries.
- Negative: tier 1 has a ≤ 20 min budget per run (hard cap `timeout-minutes: 30`), cannot detect
  statistical regressions (n = 20), and its judged numbers depend on GitHub Models quotas; small CPU
  models are weaker than the A40 models, so tier-1 numbers are a smoke signal and tier 2 is the
  authoritative, statistical gate. Nondeterminism is controlled by temperature 0, fixed seeds, pinned
  model files, llama.cpp `--parallel 1` and judge caching.
