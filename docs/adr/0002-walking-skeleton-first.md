# 0002 — Walking-skeleton-first phase order

- Status: Accepted
- Date: 2026-10-27 (revised 2026-10-31: round 9 X5.6, X3.11)
- Tasks: all of Phase 1

## Context
Spec v1 ordered the phases corpus → app → dataset → judges → gate. With that order the gate, which is
the actual product, would first run end-to-end around week 6, after human labeling and dataset
publishing. Modules built by separate AI sessions would only meet at that point, so integration
problems would show up late and cost a lot to fix.

## Decision
Phase 1 builds a thin **real** end-to-end path on CPU (revised 2026-10-28, ADR-0008; revised 2026-10-31, round 8 W1):
real 5-law slice (T2.1/T2.2) → rag-demo v0 (BM25 + small dense model, llama.cpp generator, real bug
switches; T1.13) → 40 hand-written fixture cases (20-case `smoke_live` subset in tier 1) → runner →
deterministic metrics (+ ≤ 10 informational judge calls via GitHub Models) → gate stats/policy (the
tier-1 gate decides on hard fails and `error_rate` only; injection, language, citation and
refusal-phrase results are reported; paired statistics are `INSUFFICIENT_DATA` at n = 20)
→ real PR comment → GitHub Action, green in tier-1 live CI on a real PR (milestone M1). The
deterministic demo PRs (whitespace → PASS, `tenant_filter: post_topk` → hard FAIL) run here; the
statistical reranker-off demo runs in tier 2 (T6.5, MVP). Each later phase deepens one stage of
this path without changing its contracts (`docs/architecture/interfaces.md`).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Spec v1 order | The gate cannot be tested until week 6, which contradicts the spec's own pitfall "ship Phase 4 end-to-end first" |
| Build the RAG app first | It is the most expensive piece and needs the GPU, so it would block everything else |

## Consequences
- Positive: the contracts are proven early on real models, every later PR is measured by a working gate, and no tier needs a GPU except tier 2.
- Negative: rag-demo v0 and the slice corpus move into Phase 1 (T1.13, T2.1, T2.2 earlier); tier 1 has a ≤ 20 min budget per run (hard cap `timeout-minutes: 30`); its judged metrics are informational and depend on GitHub Models quotas, so the statistical gate is first proven in tier 2.
- Follow-up: the fixtures must cover every category so the slicing logic is exercised.
