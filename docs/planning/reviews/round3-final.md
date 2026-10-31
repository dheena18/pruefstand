# Round 3 — final verification

Scope: all `*.md` outside `docs/planning/` and `docs/spec/SPEC-v1-original.md`, checked against
`round2-resolution.md` (Q1–Q5) plus: two Apps (`pruefstand-bot` gate, `pruefstand-release` release-please only),
no-op WARN-or-FAIL bound 0.12, bootstrap small-sample correction, absolute checks gated on `overall` only.

Result: 16 findings (0 blocker, 0 high, 11 medium, 5 low). Verified clean: `gate-dispatch` (only "there is no ..." mentions),
one Holm family, `warn_p` 0.10, `robust_pr` = 40 bases (except F5), signed baselines (removed everywhere except history rows),
`sign-blob` (rejected-alternative only), `12-16 weeks` (none; 20-26 / week 12-14 consistent), T0.6 (all links present),
`model_families.yaml` (single table), `DiskKVCache` (T1.8 / T5.1 / T6.1 consistent), cause codes (no "rule N"), cron `0 0 * * *`,
`gpu-cluster` concurrency, `id-token` allowlist, required-check list, 0 approvals, every TASKS.md ID has a prompt file,
every `prompts/README.md` link resolves, 72 of 73 prompt "Depends on" rows equal TASKS.md (after dropping parenthetical notes).

| id | severity | file:line | problem | exact fix |
| --- | --- | --- | --- | --- |
| F1 | medium | prompts/T9.3-technical-report.md:31 | Report outline says "Holm per metric" (Q1.1: one Holm family per run). | Replace `Holm per metric` with `one Holm family per run`. |
| F2 | low | REVIEW.md:97 | ADR index row says "Holm per metric" for 0007 (ADR is now one family). | Replace `Holm per metric` with `one Holm family per run`; change "revised in round 1" to "revised in rounds 1-2". |
| F3 | medium | docs/spec/SPEC.md:710-711 | Full-gate no-op bound `warn`-or-`fail` rate ≤ 0.10; ADR-0007:45, D57, T1.7, T6.3 use ≤ 0.12. | Change `≤ 0.10` to `≤ 0.12` (end of line 711). |
| F4 | medium | docs/engineering/testing-strategy.md:87 | Same bound: `warn`-or-`fail` rate ≤ 0.10. | Change `≤ 0.10` to `≤ 0.12`. |
| F5 | medium | prompts/T3.1b-model-benchmark.md:44 | PR-tier estimate uses `robust_pr 330 queries`; Q1.4 / D55 / SPEC §3 / gpu-cluster.md:111 say 440 (40 x 11). | Change `robust_pr 330 queries` to `robust_pr 440 retrieval-only queries`. |
| F6 | medium | prompts/_review.md:4-5 | "Run Copilot code review on the PR as a second ... reviewer" (Q2.8: Copilot optional; default is `gh models run`). | Replace sentence with: `Run the second-family review with GitHub Models (gh models run <model> < review-input.md); Copilot code review is optional.` |
| F7 | medium | prompts/_session-start.md:9 | "CI runs. Copilot code review runs." | Replace with `CI runs. Run the second-family review: gh models run <model> < review-input.md (Copilot code review is optional).` |
| F8 | medium | prompts/_session-start.md:22 | Table says "GitHub Copilot code review (other model family, included in GitHub Pro)"; false per Q2.8 / D67. | Replace the cell with `GitHub Models via gh models run (other model family); Copilot code review optional (not in GitHub Pro)`. |
| F9 | medium | prompts/T5.1-llm-hardening.md:6 | "Depends on" is `T1.4, T3.1b`; TASKS.md:93 says `T1.4, T1.8, T3.1b` (T5.1 needs `DiskKVCache` from T1.8, Q4.3). | Set the row to `T1.4, T1.8, T3.1b`. |
| F10 | medium | tasks/TASKS.md:129 + prompts/T8.5-deploy-cd.md:6,109 | Core task T8.5 depends on optional T8.4 and uses its budget cap; skipping T8.4 (Q5.2) blocks M6. | In TASKS and the prompt: `T8.3, T7.2` (+ `T8.4` only if done); say in T8.5 that the demo API budget cap comes from T8.4 when present, else deploy dashboard only. |
| F11 | medium | tasks/TASKS.md:137 + prompts/T9.2-readme-quickstart.md:6,19 | Core task T9.2 depends on optional T9.1b (Marketplace repo) and reads `action/README.md (T9.1b)`. | Depends: `T9.1a, T7.4`. Line 19: read `action/README.md` (T1.12); quickstart uses `uses: <GH_OWNER>/pruefstand/action@vX` per Q5.2; mention the Marketplace only if T9.1b is done. |
| F12 | medium | CLAUDE.md:39-41 and docs/decisions.md:95 vs prompts/T0.1-repo-scaffold.md:56 | CLAUDE.md says testpaths is "exactly this list" (5 entries); T0.1 sets 9 entries (`scripts/tests`, `tests`, `benchmarks/tests`, `experiments`); later tasks (T5.3, T6.2a, T7.1a, T7.4, T9.1b) add more. Q3.3 list and T0.1 disagree. | Make one list the truth: add `scripts/tests`, `tests`, `benchmarks/tests`, `experiments/*/tests` to D71 and CLAUDE.md:39 and replace "exactly this list" with "this list (append-only)"; or cut T0.1:56 to Q3.3's five. Fix the T6.2a:98 `infra/*/…/tests` claim to match. |
| F13 | low | tasks/TASKS.md:38 vs prompts/T1.1-core-models.md vs prompts/T1.6-gate-stats.md:57 | TASKS puts `CauseCode` in T1.1; T1.1 prompt does not list it; T1.6/T1.7 say it is created in T1.7 (`core/models/gate.py`). | Remove `CauseCode` from the T1.1 row in TASKS.md (it belongs to T1.7). |
| F14 | low | docs/adr/0017-release-automation.md:14 | ADR-0005:40 refers to ADR-0017 for `pruefstand-release`, but 0017 only says "a GitHub App token" and never names the App or its limits. | Line 14: write `GitHub App token (App pruefstand-release: contents + pull_requests write, used only by release-please.yml; the gate App is pruefstand-bot)`. Same wording in SPEC.md:504, ci-cd.md:39, release.md:23. |
| F15 | low | docs/decisions.md:39-50 (D22, D24, D28, D30-D33) | Superseded rows still say "Holm family = one metric" (D24), `repository_dispatch` from `gate-dispatch.yml` (D31), "signed" baselines (D33) with no marker; a prompt that cites them can follow the old rule. | Prefix each superseded row with `[superseded by D5x/D6x]` (D24 by D51, D28 by D56, D30 by D55, D31 by D61, D32 by D62, D33 by D63, D22/D23 by D51/D52/D54). |
| F16 | low | prompts/T0.0-bootstrap.md:92,119 | Q4.5: prompts never reference `.review/`; T0.0 names it twice (move instructions). | Reword: `if the pre-existing review folder from the planning phase exists, move it to docs/planning/reviews/`; drop the literal `.review/` at lines 92 and 119. |
