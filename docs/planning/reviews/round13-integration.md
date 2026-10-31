# Round 13 integration log

Integrator pass after the four fixers applied `round13-resolution.md`. Binding integrator decisions are recorded
as D319–D323 in `docs/decisions.md` (ranges updated in CLAUDE.md, prompts/README.md, REVIEW.md).

## 1. Items applied

| # | Item | D-row | Files |
| --- | --- | --- | --- |
| 1 | Judge `num_ctx` = **12 288 for both judges** (PR `mistral`, nightly `gemma`); input cap 11 264; T3.1b may lower it only if its VRAM measurement fails (after 2 slots). All "10 240" pins and the PR judge's 16 384 removed; D306 kept | D319 (D204, D306 refined) | SPEC §6.3 model table (PR + nightly judge rows), VRAM paragraph, judge input cap; gpu-cluster §2.1 rule + §3 VRAM table (GPU1 day/night rows) + GPU1 note; ADR-0009; runbook mode switch; sequences (`switch-mode.sh night`); interfaces (catalogue `num_ctx` + D306 line); T3.1a (catalogue rule + `test_catalogue.py` bound 12 288); T3.1b (judge context step, SWA numbers, test row); T5.1; T5.2a |
| 2 | `demo-net` `--internal` (10.232.0.0/24); `cloudflared` 10.232.0.2 on `demo-net` + `demo-egress` (10.233.0.0/24, created by `setup-proxy-net.sh`); RFC 1918 drop applies to `demo-egress`; `PRUEFSTAND-INPUT` drops both subnets | D320 (D291 annotated) | T0.7 (P2.2 paragraph, firewall file line, S5b, test row, `vm_check` probes, HUMAN Done-when); T8.4 (compose network); T8.5 (Hosting paragraph, S5); docker.md; security.md D4; runbook §0.3 + optional-demo section; ADR-0012; deployment.md; test-matrix demo row; ui-spec §4.6; TASKS T0.7 |
| 3 | Release drift anchor = `release-b0..b2`, written only by the **release run of all of `full`** (newest tag image, alone on its night instead of the block run, never gated, retried each night via `release-run-due` until all three refs exist for the current fingerprint); `promote --ref release-b<k>` writes the block-*k* projection under the block-*k* fingerprint. Flagged runs (judge fallback/drift/degraded/truncated, `infra_error`) are never promoted to any ref | D321 (D305, D309, D224 annotated) | SPEC §6.2 (baselines, phase order, flagged runs), §7 cumulative drift, §judge fallback; interfaces §7 (refs + promotion), §1 `judge_fallback` comment, §15 run/gate/promote; sequences (promote text + nightly diagram); ADR-0004, ADR-0007; ci-cd (`baseline-promote.yml` + `nightly.yml` rows, mermaid); gpu-cluster §5 nightly row; runbook (`drift: no release baseline`); test-matrix (refs, gate refs, nightly, flagged-promotion rows); T6.1 (refs, release anchor, drift, refusal rule, S7, file list `store/promote.py`, tests); T6.2b (`baseline-promote.yml`, `nightly.yml` release run + drift, S4 `release-run-due`, `promotable-nightly`, `test_nightly.py`, `test_promote.py`, CLI block); T1.10; T5.1; TASKS T6.1/T6.2b; REVIEW.md. T7.x: no release-anchor text found, nothing to change |
| 4 | Core docs mirror the non-UI prompt fixer: `eval_fingerprint(..., stratum=)` hashed only when not `all`; `is_drift(..., threshold=)` and catalogue `tokenizer: {source, sha256}` (already present, verified); `gate-executor.yml` dispatch-only with group `${{ github.workflow }}-${{ inputs.pr \|\| inputs.sha }}`; release exemption posted by `gate-router.yml` via the patch-line regex; `--block auto` reads the file named by `PRUEFSTAND_NIGHTLY_COUNTER` (unset → `$PRUEFSTAND_HOME/state/nightly_counter`; missing → 0, invalid → exit 2) | D322 (D298, D299 annotated) | interfaces (fingerprint comment, gate trigger, gate router, `--block auto`); data-model; test-matrix (fingerprint + CLI rows); ADR-0005; ci-cd §5; secrets.md; `.env.example`; T1.10 (text, CLI comment, test) |
| 5 | `release-demo-ready` (`contents: write`) and `fetch-artefacts` (`actions: read`) live in `demo-ready.yml`; the guard allowlist names exactly these | D323 | T0.2 (allowlist rule + `test_check_workflows.py` cases; was `release.yml` / `deploy.yml`); T8.5 (allowlist note); TASKS T0.2; test-matrix `check_workflows` T8.5 row; ci-cd §1.1 already correct |
| 6 | Depends-on check + stale sweep | – | §2, §3 |

## 2. Stale-term sweep (excluding `docs/planning/`, archived SPEC-v1)

| Term | Result |
| --- | --- |
| `run-gate` | only negative/historical statements ("no `run-gate` label", superseded rows, ADR-0005 alternatives, guard tests); REVIEW.md round-8 summary reworded |
| `10240` / `10 240` | none, except D306's own text ("10 240" dropped) |
| `release-full-due` | none, except the D305 annotation naming what D321 supersedes |
| `label event` | none outside superseded decision rows; TASKS T6.2a and REVIEW.md now say "at dispatch time (D288)" |
| `'poll'` | none |
| `max-model-len` | only "never/no `max-model-len`" statements and D307 |
| `/dashboard/` (URL) | none; remaining hits are file paths (`apps/dashboard/`, `scripts/dashboard/`) and D243/D268 history |
| `Vercel` | only "dropped"/alternatives rows, negative tests (`no VERCEL_*`) |
| `network_mode: host` | only D215 (superseded), the rejected placement in deployment.md, "never" in T6.2a/interfaces, T3.2 dev `rag-demo-dev`, T0.3 linter test case |

## 3. Checks

- Prompt "Depends on" vs `tasks/TASKS.md` Depends (first row per ID, escaped `\|` handled): 76 prompts, **0 mismatches**.
- No encoding damage (mojibake scan) and no mixed line endings in any `.md` or `.env.example`.
- test-matrix row count unchanged (edits only inside existing rows).
