# Round 8 resolution — binding decisions (cold read 4, four lenses)

Inputs: `round8-dev.md` (30), `round8-ai.md` (38), `round8-ui.md` (28), `round8-arch.md` (54).
Overrides earlier resolutions where they conflict. Where silent, apply the reviewer's exact fix.

## W1 Tier-1 live CI that actually fits (AI-01, AI-02)

| # | Decision |
| --- | --- |
| W1.1 | Tier-1 PR run uses a new split **`smoke_live`** = 20 cases chosen by rule from the 40 fixtures: ≥ 1 leak probe per tenant, 2 refusal, 2 injection, 1 system-prompt probe, rest factual with citations. `Split` enum gains `SMOKE_LIVE`. |
| W1.2 | Tier-1 generator ≤ 2B params, GGUF Q4_K_M, **thinking disabled** (Qwen3: `enable_thinking=false` / `/no_think` in the chat template; documented for every Qwen3 use in all tiers). Tier-1 RAG settings: `top_k: 4`, chunk text truncated to 256 tokens for the prompt, `max_tokens: 256`, `reranker: off`. Budget per run ≤ 20 min, `timeout-minutes: 30`. |
| W1.3 | **Tier-1 gate decides on deterministic checks only**: hard fails (canary, tenant, system-prompt leak), absolute checks (injection_success, error_rate), and the language/citation/refusal-phrase checks reported. Paired statistics are `INSUFFICIENT_DATA` at n = 20 and say so. The statistical gate is tier 2. |
| W1.4 | Judged metrics in tier 1 are **informational**: at most 10 cases per PR, judged through GitHub Models, cached. If the quota is exhausted they are skipped and marked `judge_mode=skipped`. No uncalibrated judge ever decides a required check. The CPU fallback judge is removed from tier 1. |
| W1.5 | The bug-switch scenario matrix runs **nightly and on PRs that touch `apps/rag-demo/**`**, as one parallel matrix job per scenario (≤ 20 min each). It asserts only deterministic outcomes (hard fail / absolute check), so it is not flaky. Scenarios that need statistics (reranker off, prompt without citations) move to **tier 2** and to the M1/MVP demos there. |
| W1.6 | GitHub Models budget: ≤ 10 calls per PR, ≤ 60 per nightly. T0.6 runs a 24-hour scheduled probe to measure the real daily limit and records it in `ci-cd.md`. |

## W2 Private executor operations (arch blockers + majors)

| # | Decision |
| --- | --- |
| W2.1 | The A40 runner is **persistent** (registered once by the owner), runs as a user service (`systemd --user` with linger, or `tmux` if linger is not allowed — T0.6 checks), and has `ACTIONS_RUNNER_HOOK_JOB_STARTED/COMPLETED` cleanup scripts: wipe the workspace, remove job containers/networks/volumes, drop PR-scoped Qdrant collections. Not ephemeral. |
| W2.2 | One concurrency group **per workflow** (`gate-executor`, `nightly`, `baseline-promote`) with `cancel-in-progress: false`; GPU mutual exclusion through `flock /home/<user>/pruefstand/gpu.lock` in the orchestrator. |
| W2.3 | Processed-work state: the executor keeps `state/processed.jsonl` (pr, head sha, label event id, result) in the private repo; it runs a PR when (label event newer than head commit) and (pr, sha, label event) is not yet processed. A `pending` status it posted itself does not block it. |
| W2.4 | Gated PR with **no baseline** for its eval fingerprint → status `failure` "no baseline for <fp>; run baseline-promote" (never pass). |
| W2.5 | Fork PRs: the maintainer pushes the reviewed head to branch `gate/pr-N` (no mirror PR). The executor accepts `workflow_dispatch` input `pr=N` and uses `gate/pr-N`; the result is posted to the original fork PR. |
| W2.6 | Gated paths add `uv.lock`, `infra/docker/**`, `infra/gpu/**`. Release PRs from release-please whose diff only touches version fields and CHANGELOG get "not gated (release version bump)". |
| W2.7 | Ruleset bypass list: repository admin (the owner) only, for cluster outages; every bypass is logged in `docs/ops/bypass-log.md`. |
| W2.8 | The rag-demo GHCR package is **public** (contains no secrets), so the executor pulls without credentials. |
| W2.9 | No token from the private repo in the public repo. The executor pushes sanitized dashboard data to a separate public repo `<GH_OWNER>/pruefstand-dashboard-data` with a fine-grained PAT scoped to that repo only, stored in the private repo. |
| W2.10 | Health: the executor writes `heartbeat.json` (timestamp, last job) to the dashboard-data repo every run; public `executor-health.yml` (hourly) opens/updates an issue if it is older than 2 h. Backups: weekly `git bundle` of the private repo + held-out canaries encrypted with `age`, kept on the cluster home and copied to the owner's laptop (runbook in `docs/ops/runbook.md`). |
| W2.11 | Retention: keep the last 20 baselines per fingerprint (monthly prune job), private artefacts 14 days. |
| W2.12 | Fix stale docs: docker.md ports, `data-model.md` uses `stack`/`workload`/`judge_mode` (no `tier`), remove `;` inside Mermaid labels. |

## W3 Models, judges, eval method (AI majors)

| # | Decision |
| --- | --- |
| W3.1 | Family plan (exact versions pinned by benchmark in T1.13/T3.1b): generator = **qwen**; PR judge (A40) = **mistral** (or gemma if mistral fails calibration); nightly judge (A40, 70B-class) = **llama**; datagen = **llama** 70B-class (≠ generator); tier-1 informational judge = a GitHub Models model of a non-qwen family. Recorded in `core/data/model_families.yaml` and gpu-cluster.md. |
| W3.2 | Judge cache key = model id + provider-reported version + prompt version + hash of **all rendered inputs** (question, answer, context chunk ids and text hashes, reference). Fix every doc that says "answer hash". |
| W3.3 | Hosted-judge drift: nightly re-judges a fixed anchor set of 20 items; if agreement with the stored verdicts < 0.9 → `judge_drift=true`, that judge's cache is invalidated and its judged metrics are informational until re-calibrated. |
| W3.4 | The faithfulness judge sees exactly the chunks the generator saw (same top_k). |
| W3.5 | Refusal is decided by the gate (phrase list + refusal judge); the target's `refused` flag is informational. |
| W3.6 | Per-metric gating needs ≥ 30 applicable clusters in the split; otherwise that metric is informational in that split. Refusal metrics are gated only in nightly `full` (≥ 100 unanswerable). Every PR comment shows MDE per gated metric. |
| W3.7 | σ_d for T6.3 is estimated from paired runs across **no-op changes** (re-index, reordered config, rebuilt image), not only identical repeats. |
| W3.8 | Calibration hard negatives: same-paragraph wrong span, number/date swap, negation flip, partially correct answer; MEMERAG "Not Supported" items. A judge passes only if κ ≥ 0.6 overall **and** ≥ 0.5 on the hard-negative subset. If no judge passes, judged metrics are informational only. |
| W3.9 | Judge failure on a case → that metric `status=ERROR, value=None`, counted; if judge errors > 5 % of cases → the run is marked `judge_degraded` and judged metrics are informational. |
| W3.10 | e5-family embeddings use `query: ` / `passage: ` prefixes; passages truncated to the model limit with a logged count. Tier 1 has no reranker; tier 2 reranker = `BAAI/bge-reranker-v2-m3` (Apache-2.0, verify) on the A40. |
| W3.11 | RQ1 chunking axis scored with chunk/span-level gold (gold citation span contained in a retrieved chunk), not doc-level recall. |
| W3.12 | Citation parser also handles English "Section 622 BGB" / "Sec. 622". |
| W3.13 | `core` split gets a 100 % model review (+ the 50-item owner spot check); `full` keeps 20 %. |
| W3.14 | `robust_pr` = 40 bases × the applicable perturbations per base (not all 11 apply); target ≈ 300–440 cases; `perturbed_all` n is reported. |
| W3.15 | No hosted generator anywhere in SPEC unless `allow_paid` and behind the data guard (off). |

## W4 Code quality and tests (dev blockers + majors)

| # | Decision |
| --- | --- |
| W4.1 | ruff: `per-file-ignores` for `tests/**`: `RUF001, RUF002, RUF003`; global ignore `TRY003`; select `T20`; `pylint.max-args = 8`, `max-positional-args = 5` (PLR0917). |
| W4.2 | Doctests run: `--doctest-modules` over `packages/pruefstand/src` (statistics docstrings carry worked examples). |
| W4.3 | pytest `pythonpath` includes `scripts`, `data`, `experiments`, `tools`, `action` so their tests import. |
| W4.4 | Coverage gate defined once in CLAUDE.md (≥ 90 % core/gate/metrics/perturb, ≥ 80 % overall, src only); other docs point to it. |
| W4.5 | Simulation suite: PR runs a reduced grid (500 sims, bound α + 4·SE); the full 4 000-sim grid runs nightly. |
| W4.6 | `export_hf(dir, repo_id, private, *, dry_run=False)`. `CassetteRecorder` is implemented in T1.4. T3.3–T3.6 move/replace the T1.13 tests of modules they replace (no deleted-module imports). T10.3 extends `adapter_contract.py`, never recreates it. |
| W4.7 | `docs/engineering/test-matrix.md` is maintained: every task's DoD includes "test-matrix rows for my symbols are `covered`". The 7 missing symbols get tests in their owning tasks. |

## W5 UI (UI blockers + majors)

| # | Decision |
| --- | --- |
| W5.1 | `docs/design/ui-spec.md` is the UI source of truth; T1.9, T6.4, T8.1–T8.5, T9.2 cite its sections. |
| W5.2 | Contracts gain: `SliceDecision.max_drop`, `SliceDecision.max_value` (or an `AbsoluteCheck` row with `max_value`); `RunIndexEntry` model (core.models.dashboard) for `runs/index.json`; per-case fields for the case page (citations, per-metric status, retrieved chunk ids); not_applicable counts; `judge_mode`/`judge_fallback` notices. |
| W5.3 | Cases list page with client-side filter over sharded `cases/<run_id>/<shard>.json`; individual case pages only for failing and top-N cases. `report.html` is exported next to run data. |
| W5.4 | i18n: static de/en dictionaries, route prefix `/de` `/en`, default `de`; licence attribution footer on every page. |
| W5.5 | Try-it API errors are JSON `{code, message, retry_after_s}` (no reliance on reading `Retry-After`); loading, timeout, refusal and budget-exhausted states. |
| W5.6 | Fixture snapshot includes runs covering pass, warn, fail, hard fail, insufficient data, partial/incomplete, judge skipped. UI tests cover every page × state × light/dark × de/en × 360 px / 1280 px, axe serious = 0. testing-strategy.md matches T8.3. |
