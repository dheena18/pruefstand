# Round 1 resolution — binding decisions

Inputs: `round1-consistency.md` (60), `round1-technical.md` (50), `round1-executability.md` (70).
This file decides every cross-cutting question. Fixers apply it; where a finding is not covered here,
apply the reviewer's concrete fix if it agrees with this file, otherwise follow this file.

## R1 Statistics (supersedes ADR-0007 rule, SPEC §7.2, interfaces §9)

| # | Decision |
| --- | --- |
| R1.1 | **FAIL rule = significant drop that is practically relevant.** H0: Δ ≥ 0. One-sided bootstrap p = P*(mean_diff* ≥ 0). FAIL iff Holm-adjusted p < α (0.025) **and** mean_diff < −δ. δ (`max_drop`) = smallest drop that matters. |
| R1.2 | **Gated slices** = `overall` + pre-registered key slices (`tenant`, `lang`; `perturbation` for retrieval metrics only) with n_clusters ≥ `min_clusters` (30). Only gated slices can FAIL or WARN. All other slices are informational "notable drops" (BH, q = 0.10) and never change the status. |
| R1.3 | **WARN** (gated slices only): mean_diff < −δ and Holm-adjusted p < 0.10, but not FAIL. |
| R1.4 | Holm family = **one metric across its gated slices**. Metrics are separate families. ADR-0007, call-graph.md, SPEC, interfaces, T1.6/T1.7 all say this. |
| R1.5 | Clustering by new field `TestCase.cluster_id` = source document of the base question (default: first gold doc id, else base_id). `base_id` stays for perturbation pairing. |
| R1.6 | Errors are not dropped: a candidate case with an error gets the worst value for every metric. New deterministic metric `error_rate` (lower is better) with an absolute check `max_value: 0.02`. If the baseline has error_rate > 0.02 → `GateInputError`. |
| R1.7 | **Absolute checks** (`max_value`, e.g. injection_success 0.02): FAIL iff Wilson 95 % lower bound > max_value; WARN iff point estimate > max_value. Plus the normal paired regression check. |
| R1.8 | Bootstrap: percentile, B = 10 000, clusters resampled. If fewer than 10 clusters have a non-zero diff, use an exact sign test on cluster mean diffs for p. n_clusters < 30 → `INSUFFICIENT_DATA`. |
| R1.9 | Every PR comment shows the **MDE** per gated metric: MDE ≈ (z₁₋α + z₀.₈)·SE_boot. New pure function `gate.stats.power_estimate(sigma_d, n_clusters, delta, alpha, m) -> float` and `minimum_detectable_effect(se, alpha, power=0.8, m=1)`; CLI `pruefstand power` (T1.10). |
| R1.10 | Simulation tests (T1.6/T1.7): σ_d ∈ {0.15, 0.25, 0.40}, n ∈ {30, 50, 300}, Gaussian and binary (2–10 % discordance). Assert with fixed seeds: type-I of FAIL at Δ = 0 ≤ α + 0.01; power at Δ = 2δ, n = 300, σ_d = 0.25, δ = 0.03 ≥ 0.80; full `evaluate_gate` overall WARN-or-FAIL rate at Δ = 0 ≤ 0.10. Power curves written as CSV artefact. |
| R1.11 | Defaults: `max_drop` 0.05 for answer_correctness, faithfulness, context_recall, citation_f1; 0.03 for refusal_correct. T6.3 measures σ_d and the no-op false-block/false-warn rates and checks MDE ≤ δ at the core size; δ is **not** set "above noise" (noise is already in the CI). If MDE > δ, increase core size. |
| R1.12 | Cumulative drift: nightly compares `main` with the last **release** baseline (`ref="release"`); FAIL opens an issue (non-blocking). |
| R1.13 | New split `ROBUST_PR`: 30 base questions × 11 perturbations, retrieval metrics only (context_recall, retrieval Jaccard), no judge; runs in the PR tier. |
| R1.14 | RQ3 is pre-registered (`experiments/rq3/PREREGISTRATION.md`, written before running) and reports detection, false-block **and false-warn** rates for all three gates, honestly even if the naive gate detects more. |

## R2 CI security and release (supersedes ADR-0005, ci-cd.md §7, security.md C*, T6.2, T9.1)

| # | Decision |
| --- | --- |
| R2.1 | **No self-hosted runner on the public repo.** The A40 runner is registered only to a private executor repo `<GH_OWNER>/pruefstand-gate`. |
| R2.2 | Public workflow `gate-dispatch.yml`: on `pull_request` (types labeled, synchronize) for **same-repo** branches with label `run-gate`, via environment `gpu-gate` (required reviewer), plus push to `main` and schedule. It sends `repository_dispatch` `{sha, pr_number, ref, tier}` to the private repo with a GitHub App token stored only in that environment. Fork PRs: a maintainer reviews, then pushes to `gate/pr-N` in the public repo (`scripts/mirror_fork_pr.sh`, which refuses diffs touching `.github/**`, `infra/runner/**` or `action/**`). |
| R2.3 | Private `gate-executor.yml` always uses **its own** workflow and orchestrator from the private repo's `main`. It checks out the public SHA only as data and builds nothing from untrusted workflow files. |
| R2.4 | Images: the public `build-images.yml` (hosted runner, no secrets) builds the rag-demo image for the SHA, pushes `ghcr.io/<GH_OWNER>/rag-demo:sha-<sha>` and signs it with cosign keyless. The executor pulls **by digest** and verifies with `--certificate-identity` = the exact build workflow path and `--certificate-oidc-issuer https://token.actions.githubusercontent.com`. Containers run under **rootless Docker** on the cluster (GPU through CDI), as an unprivileged user. |
| R2.5 | The executor posts the PR comment and commit status back through a GitHub App (pull_requests: write, statuses: write only). Public comments are **redacted**: no chunk text, canary tokens masked. Full artefacts stay in the private repo. |
| R2.6 | Caches: only main/nightly jobs write shared caches. PR jobs read the main cache plus a PR-scoped overlay that is discarded after the job. |
| R2.7 | Baselines live in the private repo, branch `baselines` (protected, no force-push), layout `baselines/<eval_fingerprint>/<ref>/`. Each baseline manifest is signed (`cosign sign-blob`, keyless) and verified before use. A sanitised copy (run.json, gate.json, results without text) goes to the dashboard data. |
| R2.8 | Held-out canaries exist only in the private repo; they are never in public artefacts, the HF dataset or logs. |
| R2.9 | release-please runs with a **GitHub App token**, so its tags trigger `release.yml`. Deploy downloads artefacts by the triggering `workflow_run` id and verifies digests; it never uses "latest". cosign verification pins the identity to `release.yml@refs/tags/v*`. |
| R2.10 | Marketplace: a separate public repo `<GH_OWNER>/pruefstand-action` with `action.yml` at the root and no workflow files, synced by the release job from `action/` (verify current Marketplace rules in T9.1b). |
| R2.11 | One tier-2 job at a time: `concurrency: gpu-cluster` in the executor. |

## R3 GPU / serving (single source: `docs/engineering/gpu-cluster.md`; other docs link to it)

| # | Decision |
| --- | --- |
| R3.1 | Day mode. GPU0: generator vLLM (~14B, AWQ/GPTQ int4, `gpu_memory_utilization` 0.70), TEI BGE-M3 embeddings (~2–3 GB with overhead), TEI bge-reranker-v2-m3 (~2–3 GB). GPU1: PR judge vLLM (different family, 12–27B int4, 0.90). Start TEI first, then vLLM. |
| R3.2 | Night mode 01:00–06:00 Europe/Berlin: 70B-class int4 judge, TP = 2, exclusive. Judgments cached per (answer, judge) so the baseline is not re-judged. Nightly `full` budget ≤ 4 h. |
| R3.3 | Model catalogue `infra/gpu/models.yaml` and endpoints `infra/gpu/endpoints.yaml` are created in **T3.1a**. A PR may only pick catalogue models; otherwise the status is `unsupported_config` (WARN, maintainer action). Swapping the generator restarts the GPU0 generator service inside the job (serialised by R2.11). |
| R3.4 | An embedding-model or chunking change → the executor builds a PR-scoped Qdrant collection `pr_<N>_<shortsha>` and deletes it after the job. |
| R3.5 | Time budgets: smoke ≤ 5 min; PR tier (core + robust_pr) ≤ 25 min; nightly ≤ 4 h. The SPEC PR-comment example shows ~18 min. |
| R3.6 | `/v1/info` gains `serving: {engine, engine_version, quantization, gpu}` and it goes into `target_fingerprint`. |

## R4 Judges

| # | Decision |
| --- | --- |
| R4.1 | One scale: faithfulness and answer_correctness are 3-point ordinal {0 wrong/unsupported, 1 partial, 2 fully} → 0 / 0.5 / 1. perturbation_consistency and refusal_judged are binary. Humans label the same scales. |
| R4.2 | Calibration: quadratic-weighted κ (3-point), Cohen's κ (binary), Spearman reported too, 95 % bootstrap CIs. Accept a PR judge if κ ≥ 0.6 and lower CI ≥ 0.5. A second annotator labels 50 items for a human–human ceiling (REVIEW Q1). |
| R4.3 | Judge-family rule is checked at config load **and** at run time against the target's reported generator (catalogue lookup of `/v1/info.models.generator`). |
| R4.4 | Robustness set: 30 answers **and** 30 contexts with judge-directed injections; average shift ≥ 0.1 fails. |

## R5 Data

| # | Decision |
| --- | --- |
| R5.1 | CC BY-SA and ODbL material is never combined in one config or derived artefact. Delete any "most restrictive license" rule. |
| R5.2 | Contamination control: in T4.7b, closed-book runs (generator without retrieval) over core; cases answered correctly closed-book get tag `closed_book_answerable`. New field `TestCase.tags: tuple[str, ...] = ()`; `tags` is an informational slice dimension. |
| R5.3 | T2.6 creates both canary sets (public + held-out, the held-out one written only to a git-ignored path and then to the private repo). T4.6 creates `canaries/retired.json` and the rotation procedure. |

## R6 Structure, contracts, executability

| # | Decision |
| --- | --- |
| R6.1 | CLI is a **package**: `pruefstand/cli/__init__.py` (Typer `app`, entry point `pruefstand.cli:app`) + `cli/<command>.py`. T0.1 creates the package. |
| R6.2 | litellm backend: `pruefstand/llm/backends/litellm.py`; fake: `llm/backends/fake.py`. |
| R6.3 | **Gate stays pure**: gate does not import `metrics`. `ScoreTable` gains `higher_is_better: bool`, filled by pipeline from the registry. |
| R6.4 | `MetricPolicy` has no direction field anywhere (fix T6.3). |
| R6.5 | likely_cause: one rule table in SPEC §7.4, implemented only in `gate/cause.py` (T1.7). T6.3 validates and tunes it but does not re-create it. |
| R6.6 | Degradations: 9 kinds (as in interfaces). Hard fails everywhere: canary_leak, tenant_leak, system_prompt_leak. injection_success is an absolute check, not a hard fail. |
| R6.7 | `def stable_hash(*parts: object) -> str` (variadic; canonical JSON of the tuple). |
| R6.8 | Single homes: fingerprints and corpus_version only in `core/fingerprint.py` (T1.1); law aliases only in `core/data/law_aliases.yaml`; rag-demo models only in `rag_demo/models.py`; judge cache key only in LLMClient. |
| R6.9 | Data paths per T2.1: `data/sources.yaml`, `data/raw/` (git-ignored), `data/manifests/`. SPEC aligned. |
| R6.10 | **Workflow names** (public): `ci.yml`, `ui.yml`, `docs.yml`, `security.yml`, `action-selftest.yml`, `build-images.yml`, `gate-dispatch.yml`, `release-please.yml`, `release.yml`, `dataset-release.yml` (owned by T9.1b), `deploy.yml`. Private: `gate-executor.yml`, `nightly.yml`, `baseline-promote.yml`. Dashboard jobs are in `ui.yml`. |
| R6.11 | `check_support` uses `LLMClient` + prompt `dataset/prompts/support_check_de_v1.txt` (no Judge): `async def check_support(c: QACandidate, chunk: Chunk, llm: LLMClient, model: str) -> FilterResult`. |
| R6.12 | Dependencies: T2.6, T4.2, T4.5 depend on T5.1 (real backends); T5.1 depends on T1.4, T3.1b. T1.3 and T1.6 depend on T1.2; T1.8 on T1.4. Parallel lane after T1.2: {T1.3, T1.4, T1.5a, T1.6}. |
| R6.13 | Phase 0: new **T0.0 (H) Bootstrap**: install the prerequisites (WSL2 Ubuntu 24.04 on Windows; git, make, uv, Python 3.12, Node 22 + pnpm, Docker, gh); create the empty public repo, `git init`, push the planning pack; turn on Copilot code review. T0.2 then has a real repo. **T0.5** runs after T0.2: branch protection with required checks = only jobs that always run (no path filters on required jobs; skip logic inside the job). |
| R6.14 | `CLAUDE.md` §3 is the single definition of Make targets; T0.1 creates all of them (working). T0.2 never redefines them. T0.1 also creates the project file `.claude/settings.json` (permissions allowlist for make/uv/pytest/pnpm; a PostToolUse hook that runs `ruff format` on edited .py files). |
| R6.15 | T1.10 "Done when" uses an inline mini fixture. T1.11 adds a deterministic generator for `datasets/fixtures/synthetic_v1` (200 cases, 100 clusters, templated German) for gate e2e, plus the 40 hand-written cases. |
| R6.16 | Tag every "Done when" line that needs one with `[GPU]`, `[NET]`, `[HUMAN]` or `[DOCKER]`. |
| R6.17 | Replace SPEC v1 section numbers with v2 headings; fix ADR paths to the real file names. |
| R6.18 | **Splits** (old file removed, two new files, TASKS updated): T1.5a citations parser / T1.5b deterministic metrics + registry; T3.1a cluster services, access, catalogue / T3.1b model benchmark and pinning; T4.7a review tool + build-dataset orchestration / T4.7b human review, closed-book tagging, v1 release; T5.2a judge module, German prompts, robustness set / T5.2b judged metrics; T6.2a executor repo, runner, orchestrator, App / T6.2b dispatch, executor, nightly and baseline workflows; T7.1a framework + M1–M10 + N1–N8 / T7.1b M11–M20; T8.2a runs list + run detail / T8.2b diff, slices, failing cases; T9.1a release-please, PyPI, GHCR, cosign, SBOM / T9.1b Marketplace repo sync + HF dataset release. Slugs: `T1.5a-citation-parser`, `T1.5b-deterministic-metrics`, `T3.1a-gpu-cluster-services`, `T3.1b-model-benchmark`, `T4.7a-review-tool`, `T4.7b-dataset-release`, `T5.2a-judges-prompts`, `T5.2b-judged-metrics`, `T6.2a-gate-executor`, `T6.2b-gate-workflows`, `T7.1a-mutations-core`, `T7.1b-mutations-extended`, `T8.2a-dashboard-runs`, `T8.2b-dashboard-diff`, `T9.1a-release-pipeline`, `T9.1b-marketplace-hf`, `T0.0-bootstrap`. |

## New / changed interface items (apply in interfaces.md)

- `TestCase`: + `cluster_id: str`, + `tags: tuple[str, ...] = ()`. `Split`: + `ROBUST_PR`.
- `ScoreTable`: + `higher_is_better: bool`, `cluster_ids` replaces `base_ids` for resampling.
- `stable_hash(*parts)`; `core/fingerprint.py`: `corpus_version(...)`, `target_fingerprint(...)`, `eval_fingerprint(...)`.
- `paired_cluster_bootstrap(...)`: p for H0 Δ ≥ 0, no `max_drop` argument; `decide(r, *, max_drop, p_adjusted, warn_p, min_clusters, gated)`.
- `power_estimate`, `minimum_detectable_effect`, `wilson_interval(k, n, confidence)`, `sign_test_p(cluster_diffs)`.
- `GatePolicy`: + `gated_slices: tuple[str, ...] = ("overall", "tenant", "lang")`, + `warn_p: float = 0.10`; `SliceDecision`: + `gated: bool`, + `mde: float | None`.
- `GateStatus`: + `UNSUPPORTED_CONFIG` (counts as WARN).
- Metric `error_rate`. `TargetInfo`: + `serving: dict[str, str]`.
- `check_support` signature per R6.11. `BaselineStore.get(eval_fingerprint, ref)` with ref ∈ {"main", "release"}.
- CLI: + `pruefstand power`.
