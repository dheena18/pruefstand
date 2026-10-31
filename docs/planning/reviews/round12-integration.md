# Round 12 integration log

Scope: reconcile the pack after the four fixers applied `round12-resolution.md`, plus six integration items
from the lead. New decision rows **D284–D286** in `docs/decisions.md` (D242, D255, D257 annotated).

## 1. Items applied

| # | Item | D-row | Files |
| --- | --- | --- | --- |
| 1 | `Runner.run(..., judged_subset: bool = False)` in interfaces §8 (T1.8 S6c, N1.2); infra_error kinds incl. `window_exceeded`, `nas_unavailable` (already in §1.5 and §2, verified); `gpu_catalogue_file` / `PRUEFSTAND_GPU_CATALOGUE` (already in interfaces, secrets.md, `.env.example`, T1.2, verified); heartbeat `last_nightly_status`, `last_nightly_at`, `*_false_since` (already in `push_heartbeat`, runbook; not env vars, so no secrets rows) | D249, D256, D272, D275 (existing) | interfaces §8, call-graph (`Runner.run(..., judged_subset)`) |
| 2 | VM fine-grained `gh` token also needs **Workflows: read and write** (pushing `.github/workflows/**` is rejected without it) | D284 (D257 annotated) | secrets.md (row + note), security.md (C18, secrets table), ci-cd §7 row (removed the contradictory "no `workflow` scope"), interfaces §1.5, ai-workflow, runbook §0 + rotation row, CLAUDE.md rule 9, `_lead-agent.md`, T0.0 S7 (was "needed only to push…"), T0.7 Context, TASKS T0.7 |
| 3 | Firewall: container → `172.17.0.1` hits `INPUT`, not `DOCKER-USER`; rules in `DOCKER-USER` (container-to-container/egress) **and** own chain `PRUEFSTAND-INPUT` hooked from `INPUT`, both by `pruefstand-firewall.service`; ruleset never flushed | D285 (amends N4.2/D255; D242 annotated) | security.md (C2, C16), docker.md (port-table note, `llm-proxy` paragraph), runbook §0.3 + component table, deployment.md (diagram node, text), interfaces §1.5, gpu-cluster §6, ADR-0005, ci-cd §7 (candidate + network rows), test-matrix VM firewall row, TASKS T0.7, REVIEW.md, T0.7 (the "verify which hook" hedge made binding: both chains always), T6.2a (proxy paragraph) |
| 4 | Mutations: M17 `kind: config` (`rag_overrides: {generation.temperature: 0.7}`); M01/M13 expect `ndcg_at_k` | D286 | SPEC §RQ3 table (M1, M13, M17 rows), testing-strategy bug-switch row M1 (was `context_recall` / `ndcg_at_k`); T7.1a/T7.1b already matched |
| 5 | `basepath-smoke` required via `ui / check`; `post-deploy-smoke` location | – | ci-cd §5 required-checks list; T0.5 required-checks table + summary block; TASKS T0.5; `ui.yml` row already had `basepath-smoke` → `check`. `post-deploy-smoke` = job of `docs.yml` (`needs: deploy`) everywhere (ci-cd, T0.4, T8.5, ui-spec); testing-strategy and test-matrix rows now name it |
| 6 | Depends-on script check + stale sweep | – | see §2, §3 |

## 2. Stale-term sweep

| Term | Result |
| --- | --- |
| `try-it` job in `ui.yml` | none; only "no `try-it` job" statements. testing-strategy Try-it row said "job `try-it`" → now `demo-e2e` of private `demo-nightly.yml` |
| `Requires=.*mnt-pruefstand` | T0.5 S-runner text still said `Requires=mnt-pruefstand.mount`, D227 → `Wants=` + `After=mnt-pruefstand.automount` (D254); others are negative statements |
| `network_mode: host` | only D215/superseded rows, rejected placement in deployment.md, the negative "never" in T6.2a/interfaces, T3.2 dev `rag-demo-dev`, T0.3 linter test case |
| `nftables.service` reload/flush | only "never" statements and negative tests |
| `/dashboard/` (URL path) | none; remaining hits are file paths `apps/dashboard/`, `scripts/dashboard/`. Also fixed stale derive path `apps/dashboard/fixtures/derive.py` → `scripts/dashboard/derive.py` in testing-strategy and ADR-0011 (D268) |
| `Vercel` | only "dropped" statements, alternatives tables, negative tests and the archived SPEC-v1 |

## 3. Checks

- Prompt "Depends on" vs `tasks/TASKS.md` Depends (first row per ID; escaped `\|` handled): 76 prompts, **0 mismatches**.
- No encoding damage (mojibake scan over all `.md` and `.env.example`).
- test-matrix row count unchanged (edits only inside existing rows).

- Follow-up: CLAUDE.md machines table firewall wording (D285) and the round-12 binding range (D284–D286 from this log) updated.
