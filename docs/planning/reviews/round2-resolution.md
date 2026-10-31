# Round 2 resolution — binding decisions

Inputs: `round2-verify.md` (15 partly-resolved round-1 items + 40 new findings) and `round2-expert.md`
(40 findings + risks). Where this file is silent, apply the reviewer's concrete fix if it agrees with
round1-resolution.md and this file. This file overrides round1-resolution.md where they conflict.

## Q1 Statistics

| # | Decision |
| --- | --- |
| Q1.1 | **One Holm family across all (gated metric × gated slice) pairs** of a run, α = 0.025 one-sided. WARN uses the same family with `warn_p` = 0.10. Replaces R1.4 everywhere (ADR-0007, SPEC §7.2, interfaces §9, call-graph, T1.6, T1.7). |
| Q1.2 | Non-gated slices: status is always **PASS**, with `notable: bool` (BH q = 0.10) for display. They never WARN or FAIL. `GateReport` gains `notable_slices: tuple[SliceDecision, ...]`. |
| Q1.3 | An absolute-check WARN makes the overall status WARN; an absolute-check FAIL makes it FAIL. |
| Q1.4 | `robust_pr` = **40** base questions × 11 perturbations (retrieval metrics only). Gated slice for robustness = `perturbed_all` (all perturbed cases vs their bases); per-perturbation slices are informational. |
| Q1.5 | MDE shown for the rule = max((z₁₋α_adj + z₀.₈)·SE, δ + z₀.₈·SE), where α_adj = α / m (m = family size). |
| Q1.6 | Simulation tests: n_sims = 4 000, fixed seeds; type-I bound = α + 3·√(α(1−α)/n_sims); full-gate no-op bounds: FAIL ≤ 0.03, WARN-or-FAIL ≤ 0.10 (they hold with Q1.1). |
| Q1.7 | likely_cause uses **string codes**, never rule numbers: `retrieval`, `generation`, `citation_format`, `language`, `refusal_policy`, `errors`, `mixed`. Tests assert codes. |
| Q1.8 | `MetricPolicy.confidence: float = 0.95` (display CI only) is in interfaces. |
| Q1.9 | likely_cause validation on real mutations moves from T6.3 to **T7.2**. T6.3 = noise / σ_d / MDE / timing only, and tests likely_cause only against FakeTarget degradations. |

## Q2 CI — simplified and safe for one maintainer (overrides R2.2, R2.5, R2.7 where they conflict)

| # | Decision |
| --- | --- |
| Q2.1 | **No secrets and no dispatch workflow in the public repo.** Delete `gate-dispatch.yml`. The private executor **pulls**: `gate-executor.yml` runs on `schedule` (every 15 min) and on `workflow_dispatch` (input `pr`). It lists open PRs in the public repo (public read API), and for each PR that touches the gated paths and carries label `run-gate`, applied by an allowlisted maintainer **after** the head commit (checked through the issue events API), it runs the gate on that head SHA. A maintainer can also run `gh workflow run gate-executor.yml -R <GH_OWNER>/pruefstand-gate -f pr=N`. |
| Q2.2 | Trusted inputs only: the executor takes the gate config (`pruefstand.yaml`), the dataset and the pruefstand package from public `main` (or the private repo), **never from the PR**. From the PR it takes only the candidate `rag.yaml` and the candidate image (built and signed by public `build-images.yml`, verified by digest). |
| Q2.3 | The candidate container gets **no GPU and no internet egress**. It sits on an internal Docker network with Qdrant, TEI and the vLLM endpoints run by the executor from the catalogue. Rootless Docker. |
| Q2.4 | **One GitHub App `pruefstand-bot`** installed on the public repo only: `statuses: write`, `pull_requests: write`, `contents: read`, `metadata: read`. The executor uses it to post commit status **`pruefstand/gate`** and the redacted comment. The private repo uses its own `GITHUB_TOKEN`. The runner is registered by the owner by hand (registration token); no App for that. |
| Q2.5 | The executor posts `pruefstand/gate` = success "not gated (no gated paths changed)" for PRs that touch no gated path, so the required check always reports. Gated paths: one list in `ci-cd.md` (`apps/rag-demo/**`, `rag.yaml`, `infra/gpu/models.yaml`, `packages/pruefstand/src/pruefstand/{gate,metrics,judges,runner}/**`, `datasets/**`). |
| Q2.6 | Baselines: plain files in the private repo branch `baselines` (no signatures; private-repo write access is the trust boundary). Promotion: `baseline-promote.yml` (schedule every 15 min, polls public `main` for new commits + `workflow_dispatch`). |
| Q2.7 | `nightly.yml` cron `0 0 * * *` (UTC, 01:00 CET) + `workflow_dispatch`. Concurrency group `gpu-cluster` on all three private workflows. |
| Q2.8 | Branch protection for a solo maintainer: PRs required, **0 required approvals**, required checks = `ci / check`, `ui / check`, `docs / build`, `security / scan`, `action-selftest / selftest`, `build-images / build`, `pruefstand/gate` (expected source: the App). Copilot code review is **optional** (not included in GitHub Pro; Copilot Pro is a separate plan). The default second-family reviewer is `gh models run` (GitHub Models) with `prompts/_review.md`. |
| Q2.9 | `id-token: write` allowed only in `build-images.yml`, `docs.yml` (Pages), `release.yml`, `deploy.yml`; T0.2/T6.2b workflow tests use exactly this allowlist. |
| Q2.10 | T0.1 lands on `main` by direct push (bootstrap exception, before protection exists); protection is switched on in T0.5. |

## Q3 Bootstrap / WSL2 (T0.0, T0.1, T0.2)

| # | Decision |
| --- | --- |
| Q3.1 | T0.0 covers: WSL2 Ubuntu 24.04; clone into the Linux filesystem (`~/code`), never `/mnt/c`; `git config core.autocrlf input`; `gh auth login` (HTTPS) + `gh auth setup-git`, remote over HTTPS; uv (official installer), Python 3.12 via `uv python install`; Node 22 via fnm, `corepack enable` for pnpm; Docker Desktop with WSL integration **or** docker-ce in WSL + `usermod -aG docker` + re-login; `make`, `jq`. Each step has a verify command. |
| Q3.2 | `.gitattributes` with `* text=auto eol=lf` (T0.1); the planning pack is normalised to LF before the first commit (T0.0 step). |
| Q3.3 | pytest uses `--import-mode=importlib`; test dirs have no `__init__.py`; mypy with `explicit_package_bases`. testpaths include `packages/*/tests`, `apps/rag-demo/tests`, `tools/*/tests`, `infra/gpu/tests`, `scripts/*/tests`. |
| Q3.4 | T0.1 creates `schemas/.gitkeep`; the Typer app uses a callback so subcommands always work (`pruefstand version`). zizmor and actionlint run via `uvx`/pinned binaries installed in the workflow. |

## Q4 Contracts and dependencies

| # | Decision |
| --- | --- |
| Q4.1 | interfaces.md wins for fingerprint signatures; `target_fingerprint` includes `models` and `serving`. T1.1 aligns with it. |
| Q4.2 | One model-family table: `packages/pruefstand/src/pruefstand/core/data/model_families.yaml` (id pattern → family). `infra/gpu/models.yaml` references families by name. A family violation always raises **`ConfigError`** (at load time, and at run time from the target's reported generator, which aborts the run with `stop_reason="aborted"`). |
| Q4.3 | `DiskKVCache` is created in **T1.8** (`store/kv.py`); T5.1 uses it; T6.1 adds `LayeredKVCache`. |
| Q4.4 | `CanaryRegistry` is a core model from T1.1; T6.1 uses it with a test fixture (no T2.6 dependency). |
| Q4.5 | Prompts never reference `.review/`. Every binding decision lives in `docs/decisions.md` and the ADRs; prompts cite those. (`.review/` moves to `docs/planning/reviews/` as history after round 2.) |

## Q5 Scope, timeline, risk

| # | Decision |
| --- | --- |
| Q5.1 | Timeline: **20–26 weeks part-time**. MVP (M4) about week 12–14. Update REVIEW, SPEC, TASKS. |
| Q5.2 | TASKS gets a **Tier** column: `core` / `optional`. Optional: T8.4 (try-it page), T9.1b Marketplace repo (the action stays usable from the monorepo as `uses: <GH_OWNER>/pruefstand/action@vX`), the nightly 70B tier (fallback: nightly uses the PR judge), a reduced RQ1 grid (1 extra embedding model instead of 2), all of P10. |
| Q5.3 | New **T0.6 (AI+H) A40 cluster feasibility check** in week 1: SSH access, Docker + NVIDIA toolkit, `nvidia-smi`, outbound HTTPS to github.com/ghcr.io/huggingface.co, a vLLM "hello" container, whether rootless Docker works, whether a runner may be installed (cluster policy). Output: `docs/engineering/gpu-cluster.md` §"Feasibility results" + a go/no-go. T3.1a depends on T0.6. If no-go: fallback = rented GPU (one 48 GB card) with the same executor design. |
