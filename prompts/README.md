# Prompts

One prompt file per task in `tasks/TASKS.md`. Each file is self-contained: what to read, goal,
subtasks, files, exact interfaces, tests to write first, constraints, "Done when" evidence, docs to
update, and a **Prompt to paste** block at the end.

## How to use

1. Follow `_session-start.md`: branch `<type>/<ID>-<slug>` (type and branch name are in the prompt's
   header table), open Claude Code in the repo root (`CLAUDE.md` loads automatically).
2. Paste the **Prompt to paste** block from the task's file. Nothing else is needed. "Done when" lines
   tagged `[GPU]`, `[NET]`, `[DOCKER]` or `[HUMAN]` need that environment or person.
3. Approve the plan only if it lists tests before implementation and stays inside the task's files.
4. Re-run every "Done when" command yourself, open the PR, let CI run; get the second-family review
   with GitHub Models (`gh models run`, see `_review.md`). Copilot code review is optional.
5. Review in a **fresh** session with `_review.md`; fix blockers/majors; squash-merge; tick the task.
   Before merging, **this task's own** rows in `docs/engineering/test-matrix.md` must be `covered` (D133); rows of
   other tasks (`planned` or not) never block the merge (R13 D296). Refer to matrix rows by symbol name, never by line
   number.
6. Work in dependency order (column "Depends" in `tasks/TASKS.md`). Tasks in the same parallel lane
   can run in separate worktrees at the same time; with several agents follow the waves in
   `tasks/PARALLEL-PLAN.md` (lead agent: `_lead-agent.md`). Sessions run on the VM via VS Code Remote-SSH.

UI prompts (T1.9, T6.4, T8.1–T8.5, T9.2) cite their sections of `docs/design/ui-spec.md`, the UI source of
truth (D134). Binding round-8 decisions are D94–D145 and binding round-9 decisions D146–D195 in
`docs/decisions.md` (source: `docs/planning/reviews/round9-resolution.md`), binding round-10 decisions D196–D210
(source: `docs/planning/reviews/round10-resolution.md`: Ollama-only cluster, TrueNAS VM as dev + executor host),
binding round-11 decisions D211–D241 (source: `docs/planning/reviews/round11-resolution.md` Y1–Y7: one VM service
user `pruefstand`, `/var/lib/pruefstand/gpu.lock` + `pruefstand-lock`, rootful Docker, dev ports `PORT_OFFSET=10000`,
`llm-proxy` on `gate-net` + `proxy-egress` (`http://llm-proxy:11500`, D242), bearer header, `POST /v1/retrieve`, native Ollama API, night window and nightly
subset, infra errors → `error`, `setsid nohup`, GitHub Pages), binding round-12 decisions D248–D283 (source:
`docs/planning/reviews/round12-resolution.md` N1–N7: `TestCase.block` / `judged_subset`, `pruefstand run --split full
--block auto` and `--judged-subset`, baseline refs `nightly-b<k>`, `llm-proxy` option policy and `/health` counters,
drift rule `max(3, ceil(0.1·n))`, NAS/firewall units, fine-grained VM token, per-root typecheck, `scripts/dashboard/derive.py`),
binding round-13 decisions D287–D323 (D319–D323 from the round-13 integration) (source: `docs/planning/reviews/round13-resolution.md` P1–P5: App-token
`gate-router.yml` + App-pinned `pruefstand/gate`, tier 2 only by owner `workflow_dispatch` (no `run-gate` label),
`full` quota and `Split.RQ1`, judged subset on generation + judging, `post_status`, `--stratum`,
`state/nightly_counter`, `release-b<k>` anchors, whole-tree dashboard publish, `demo-ready.yml`, `build-id.txt`);
where a prompt and a D-row disagree,
the newer D-row wins and the prompt is fixed in the same PR. Before merging, re-derive the task's rows in
`docs/engineering/test-matrix.md` from the prompt's "Tests to write first" table (real file names; D182).

Support files: [`_TEMPLATE.md`](_TEMPLATE.md) (structure every prompt follows) ·
[`_session-start.md`](_session-start.md) (session playbook, model choice) ·
[`_review.md`](_review.md) (PR review checklist).

## Index

| ID | File | Task | Who | Tier |
| --- | --- | --- | --- | --- |
| T0.0 | [T0.0-bootstrap.md](T0.0-bootstrap.md) | Prerequisites on the TrueNAS VM first (WSL2 optional), LF, gh HTTPS, verify commands, empty repo, push planning pack (checklist) | H | core |
| T0.1 | [T0.1-repo-scaffold.md](T0.1-repo-scaffold.md) | Repo scaffold, uv workspace, all Make targets (typecheck per root, R12), import-linter, `.claude/settings.json` | AI | core |
| T0.2 | [T0.2-ci-pipeline.md](T0.2-ci-pipeline.md) | CI (`ci.yml`, `security.yml`), coverage gates, workflow guard (only `gate-router.yml` may use `pull_request_target`, D152), Dependabot, PR template | AI | core |
| T0.3 | [T0.3-docker-compose.md](T0.3-docker-compose.md) | Dockerfile template, compose profiles, image build + Trivy in `build-images.yml` | AI | core |
| T0.4 | [T0.4-docs-site.md](T0.4-docs-site.md) | mkdocs site, Mermaid, module graph, Pages deploy | AI | core |
| T0.5 | [T0.5-github-setup.md](T0.5-github-setup.md) | Branch protection (0 approvals), required checks, GitHub App `pruefstand-bot`, Pages (checklist) | H | core |
| T0.6 | [T0.6-cluster-feasibility.md](T0.6-cluster-feasibility.md) | Cluster + NAS facts check (Ollama, model metadata, NAS read throughput, tunnel API with `think: false`) + GitHub Models quota with a 24-hour probe, go/no-go (week 1) | AI+H | core |
| T0.7 | [T0.7-truenas-vm-setup.md](T0.7-truenas-vm-setup.md) | TrueNAS VM `pruefstand-exec`: Remote-SSH dev host, service user `pruefstand`, `/var/lib/pruefstand` + `pruefstand-lock`, NAS automount unit, VM→cluster SSH key, `pruefstand-tunnel.service`, `vm_check.sh` (R11) | AI+H | core |
| T1.1 | [T1.1-core-models.md](T1.1-core-models.md) | `core`: ids, enums, shared models, protocols, hashing, fingerprint, logging, schemas | AI | core |
| T1.2 | [T1.2-config.md](T1.2-config.md) | `core.config` package (`run`/`target`/`gate`/`build`, R13 D313): typed config, loader, validators, settings | AI | core |
| T1.3 | [T1.3-adapters.md](T1.3-adapters.md) | HTTP adapter, target API v1 contract tests (against the real rag-demo) | AI | core |
| T1.4 | [T1.4-llm-minimal.md](T1.4-llm-minimal.md) | LLMClient with real backends (llama.cpp, Ollama, GitHub Models), LLMPolicy (free only), budget, recorder, prompt registry, cassettes | AI | core |
| T1.5a | [T1.5a-citation-parser.md](T1.5a-citation-parser.md) | `core.citations`: parser, `normalise(granularity)`, `citations_match`, law aliases | AI | core |
| T1.5b | [T1.5b-deterministic-metrics.md](T1.5b-deterministic-metrics.md) | Deterministic metrics (incl. `error_rate`, `citation_grounded`, report-only `system_prompt_similarity`, D162) + registry | AI | core |
| T1.6 | [T1.6-gate-stats.md](T1.6-gate-stats.md) | Paired cluster bootstrap, sign test, one Holm family + BH, Wilson, MDE/power, `decide` | AI | core |
| T1.7 | [T1.7-gate-policy.md](T1.7-gate-policy.md) | Gated/informational slices, absolute checks, hard fails, `evaluate_gate`, `likely_cause` | AI | core |
| T1.8 | [T1.8-runner-store.md](T1.8-runner-store.md) | Async runner, retries, errors as worst value, budget stop, ArtifactStore, DiskKVCache | AI | core |
| T1.9 | [T1.9-report.md](T1.9-report.md) | PR comment (MDE, redaction), JSON report, GitHub publisher (`set_check` + `post_status`, R13), `labels.schema.json` | AI | core |
| T1.10 | [T1.10-pipeline-cli.md](T1.10-pipeline-cli.md) | Pipeline + CLI package, `power`, `corpus_mismatch`, exit codes, `--split`/`--block`/`--judged-subset` (R12), `--stratum`, `--block auto` from `state/nightly_counter` (R13) | AI | core |
| T1.11 | [T1.11-fixtures-e2e.md](T1.11-fixtures-e2e.md) | 40 hand-written cases (20 `smoke_live` by rule + 20 `smoke`) on the real 5-law slice + e2e on the real `live` stack (deterministic bug-switch outcomes) | AI+H | core |
| T1.12 | [T1.12-github-action.md](T1.12-github-action.md) | Docker Action + **`live-e2e.yml` (tier 1: `smoke_live`, gate on hard fails + `error_rate`, everything else reported; baselines `live-baseline` / `live-baseline-nightly`, D149, D188)** + bug-switch matrix + `action-selftest.yml` (M1) | AI | core |
| T1.13 | [T1.13-rag-demo-v0.md](T1.13-rag-demo-v0.md) | rag-demo v0: real BM25 + CPU embeddings + Qdrant + ≤ 2B llama.cpp (thinking off), tier-1 profile, bug switches, compose `live` | AI | core |
| T2.1 | [T2.1-data-downloads.md](T2.1-data-downloads.md) | Download scripts (incl. MEMERAG), `data/sources.yaml`, pinned manifests, checksums, licence-field check; early lane | AI | core |
| T2.2 | [T2.2-gii-loader.md](T2.2-gii-loader.md) | Gesetze-im-Internet XML loader + § chunker | AI | core |
| T2.3 | [T2.3-oldp-loader.md](T2.3-oldp-loader.md) | Open Legal Data decisions loader + section chunker | AI | core |
| T2.4 | [T2.4-eurlex-loader.md](T2.4-eurlex-loader.md) | EUR-Lex DE/EN loader + article chunker + alignment | AI | core |
| T2.5 | [T2.5-tenants-ingest.md](T2.5-tenants-ingest.md) | Tenant plan, `pruefstand ingest`, corpus versioning | AI | core |
| T2.6 | [T2.6-private-docs-canaries.md](T2.6-private-docs-canaries.md) | Synthetic private docs, canaries, held-out canary set | AI+H | core |
| T3.1a | [T3.1a-gpu-cluster-services.md](T3.1a-gpu-cluster-services.md) | One Ollama server on the cluster for both GPUs (ADR-0018; reused, else `setsid nohup`; models on the NAS, `cluster.env`), `infra/cluster/` scripts, VM-side `switch-mode.sh` / `health.sh --repair` / `fetch-model.sh` (D151, D207, D208), catalogue, endpoints, `rerank-cpu` | AI+H | core |
| T3.1b | [T3.1b-model-benchmark.md](T3.1b-model-benchmark.md) | Model shortlist benchmark through Ollama (quality, tok/s, VRAM, first load), pinning by tag + digest, PR/nightly budgets | AI+H | core |
| T3.2 | [T3.2-rag-app-skeleton.md](T3.2-rag-app-skeleton.md) | rag-demo v1 (extends T1.13): `rag_demo/models.py`, `/v1/info` serving, A40 endpoints | AI | core |
| T3.3 | [T3.3-german-analyzer.md](T3.3-german-analyzer.md) | German analyzer + sparse encoder | AI | core |
| T3.4 | [T3.4-indexer.md](T3.4-indexer.md) | Dense encoder, Qdrant collection, indexer | AI | core |
| T3.5 | [T3.5-retriever.md](T3.5-retriever.md) | Hybrid retrieval, in-query tenant filter, RRF, reranker (top 10, 256 tokens), `POST /v1/retrieve` (R11) | AI | core |
| T3.6 | [T3.6-generator.md](T3.6-generator.md) | Generation, citations, refusal, injection guard | AI | core |
| T3.7 | [T3.7-tenant-isolation-tests.md](T3.7-tenant-isolation-tests.md) | Tenant isolation + quality tests (M2) | AI+H | core |
| T4.1 | [T4.1-dataset-manifest-splits.md](T4.1-dataset-manifest-splits.md) | Dataset manifest, cluster-aware splits incl. `ROBUST_PR`, nightly blocks + judged subset (R12), `full` quota, `rq1` split, subset incl. injection (R13), HF export | AI | core |
| T4.2 | [T4.2-qa-generation.md](T4.2-qa-generation.md) | QA generation with versioned prompts | AI | core |
| T4.3 | [T4.3-qa-filters.md](T4.3-qa-filters.md) | Support check, overlap, near-dup filters | AI | core |
| T4.4 | [T4.4-perturb-deterministic.md](T4.4-perturb-deterministic.md) | Deterministic German perturbations | AI | core |
| T4.5 | [T4.5-perturb-llm.md](T4.5-perturb-llm.md) | LLM-assisted perturbations + validity check | AI | core |
| T4.6 | [T4.6-attacks.md](T4.6-attacks.md) | Injection docs, probes, refusal cases, canary rotation | AI | core |
| T4.7a | [T4.7a-review-tool.md](T4.7a-review-tool.md) | Review tool + `build-dataset` orchestration | AI | core |
| T4.7b | [T4.7b-dataset-release.md](T4.7b-dataset-release.md) | Cross-family model review (100 % `core`, 20 % `full`) + owner spot-check, closed-book tags, v1 HF release (M3) | AI+H | core |
| T5.1 | [T5.1-llm-hardening.md](T5.1-llm-hardening.md) | JSON repair, retries, judge cache key (model version + all inputs), GitHub Models quota (skip, no CPU fallback), opt-in free tiers | AI | core |
| T5.2a | [T5.2a-judges-prompts.md](T5.2a-judges-prompts.md) | Judge module, German prompts, robustness set | AI | core |
| T5.2b | [T5.2b-judged-metrics.md](T5.2b-judged-metrics.md) | Judged metrics + run-time family check | AI | core |
| T5.3 | [T5.3-calibration-sets.md](T5.3-calibration-sets.md) | Calibration label sets from existing human data (MEMERAG-DE, GermanQuAD, GermanRAG) + in-domain `legal_hard` (D161); two PRs (D210) | AI | core |
| T5.3-opt | [T5.3-opt-human-labels.md](T5.3-opt-human-labels.md) | Optional: 100 hand labels by a German speaker | AI+H | optional |
| T5.4 | [T5.4-judge-calibration.md](T5.4-judge-calibration.md) | RQ2 judge calibration (κ ≥ 0.6 full set and specificity ≥ 0.80 on hard negatives, Wilson lower ≥ 0.70, D146), choose PR + tier-1 judge by family plan, 50 drift anchors (D164) | AI | core |
| T6.1 | [T6.1-baseline-store-cache.md](T6.1-baseline-store-cache.md) | Baseline stores (plain files, refs `main`/`nightly-b<k>`/`release-b<k>`, R12/R13), RunIndex, target cache, whole-tree `push_dashboard_data` (R13) | AI | core |
| T6.2a | [T6.2a-gate-executor.md](T6.2a-gate-executor.md) | Private executor repo, persistent runner on the VM (user `pruefstand`) + cleanup hooks, GPU lock, processed state, `llm-proxy` (`gate-net` + `proxy-egress`, D242), isolated candidate (no GPU, no egress), 15-min heartbeat, infra error → `error` + one retry (R11) | AI+H | core |
| T6.2b | [T6.2b-gate-workflows.md](T6.2b-gate-workflows.md) | `build-images.yml` (head SHA), `executor-health.yml`, `gate-router.yml` (D152; App token from environment `gate-router`, R13 D287); dispatch-only PR executor (R13 D288), nightly (22:00–06:00 Berlin, refusal stratum + block k vs `nightly-b<k>`, R12), weekly cause-switches, baseline-promote (per-workflow concurrency); encrypted backups + laptop receipt, retention | AI | core |
| T6.3 | [T6.3-noise-thresholds.md](T6.3-noise-thresholds.md) | Noise study, σ_d from no-op changes, MDE check, timing; likely_cause + statistical scenarios in tier 2 | AI | core |
| T6.4 | [T6.4-html-evidence.md](T6.4-html-evidence.md) | HTML report + evidence record JSON | AI | core |
| T6.5 | [T6.5-mvp-demo-prs.md](T6.5-mvp-demo-prs.md) | MVP demo PRs (M4) | AI+H | core |
| T7.1a | [T7.1a-mutations-core.md](T7.1a-mutations-core.md) | Mutation framework, M1–M10, N1–N8, RQ3 pre-registration | AI | core |
| T7.1b | [T7.1b-mutations-extended.md](T7.1b-mutations-extended.md) | Mutations M11–M20 | AI | core |
| T7.2 | [T7.2-rq3-gate-benchmark.md](T7.2-rq3-gate-benchmark.md) | RQ3: our gate vs naive gates (true-effect reference, should-detect stratum, R13 D294); likely-cause validation | AI | core |
| T7.3 | [T7.3-rq1-grid.md](T7.3-rq1-grid.md) | RQ1 perturbation grid (reduced) + heatmap; owns `evidence_recall` (D162) | AI | core |
| T7.4 | [T7.4-make-experiments.md](T7.4-make-experiments.md) | `make experiments` reproducibility + mutmut (M5) | AI | core |
| T8.1 | [T8.1-dashboard-scaffold.md](T8.1-dashboard-scaffold.md) | Next.js scaffold, TS types from schemas, run index, sharded cases, `report.html` export, `ui.yml`, fixtures via `scripts/dashboard/derive.py` (R12), `_empty` param (R11) | AI | core |
| T8.2a | [T8.2a-dashboard-runs.md](T8.2a-dashboard-runs.md) | Runs list + run detail, de/en i18n (`/de` default), licence footer | AI | core |
| T8.2b | [T8.2b-dashboard-diff.md](T8.2b-dashboard-diff.md) | Diff, slice charts, cases list (client-side filter) and failing-case pages | AI | core |
| T8.3 | [T8.3-ui-test-harness.md](T8.3-ui-test-harness.md) | Playwright, visual regression, axe, Lighthouse (page × state × theme × locale × viewport) | AI | core |
| T8.4 | [T8.4-demo-api-tryit.md](T8.4-demo-api-tryit.md) | Demo API hardening + "Try it" page (on the VM behind a Cloudflare Tunnel, R11) | AI | optional |
| T8.5 | [T8.5-deploy-cd.md](T8.5-deploy-cd.md) | Deployment + CD to GitHub Pages (dashboard-only `deploy.yml`), `demo-ready.yml` with the pre-deploy leak-probe job (D158, R13 D318) and hash-based `<meta>` CSP (D235) (M6) | AI+H | core |
| T9.1a | [T9.1a-release-pipeline.md](T9.1a-release-pipeline.md) | release-please (App token), PyPI, GHCR + cosign + SBOM | AI+H | core |
| T9.1b | [T9.1b-marketplace-hf.md](T9.1b-marketplace-hf.md) | Marketplace action repo sync + HF dataset release | AI+H | optional |
| T9.2 | [T9.2-readme-quickstart.md](T9.2-readme-quickstart.md) | README + fresh-machine quickstart test | AI | core |
| T9.3 | [T9.3-technical-report.md](T9.3-technical-report.md) | Technical report (M7) | AI+H | core |
| T9.4 | [T9.4-blog-linkedin.md](T9.4-blog-linkedin.md) | Blog + LinkedIn post | H | core |
| T10.1 | [T10.1-mcp-server.md](T10.1-mcp-server.md) | MCP server | AI | optional |
| T10.2 | [T10.2-evidence-pdf.md](T10.2-evidence-pdf.md) | Evidence record PDF | AI | optional |
| T10.3 | [T10.3-framework-adapters.md](T10.3-framework-adapters.md) | LangChain / LlamaIndex / Haystack adapters | AI | optional |
| T10.4 | [T10.4-drift-monitoring.md](T10.4-drift-monitoring.md) | Drift monitoring on production logs | AI | optional |

Split in round 1 (old files removed): T1.5 → T1.5a/b · T3.1 → T3.1a/b · T4.7 → T4.7a/b · T5.2 → T5.2a/b ·
T6.2 → T6.2a/b · T7.1 → T7.1a/b · T8.2 → T8.2a/b · T9.1 → T9.1a/b. New: T0.0.
Added in round 4: T1.13 (rag-demo v0), T5.3-opt; T5.3 renamed (`T5.3-human-labeling.md` → `T5.3-calibration-sets.md`). No prompt uses a fake LLM or fake target. Added in round 2: T0.6 (cluster feasibility). Tier `optional` = can be skipped without breaking the MVP
or the RQ results (`tasks/TASKS.md`, "Optional scope"). Round 8: no new task IDs; work moved between tasks is
marked **R8** in `tasks/TASKS.md` (statistical bug-switch scenarios T1.11 → T6.3/T6.5; executor health, backups
and retention in T6.2b; `CassetteRecorder` stays in T1.4).
Round 9: no new task IDs; new owners are marked **R9** in `tasks/TASKS.md` (T3.1a GPU scripts, T5.3 `legal_hard`,
T7.3 `evidence_recall`, T8.5 pre-deploy leak probes, T6.2b `gate-router.yml`).
Round 10: new **T0.7** (TrueNAS VM setup; T3.1a and T6.2a depend on it); T0.6, T3.1a, T3.1b rewritten for
Ollama on the cluster; T6.2a builds `llm-proxy`; changes marked **R10** in `tasks/TASKS.md`.
Round 11: no new task IDs; changes marked **R11** in `tasks/TASKS.md` (T3.5 owns `POST /v1/retrieve`; T3.4/T3.6 own
the bearer header, T1.13 sends it from day 1; T0.7 creates the `pruefstand` identity and lock wrapper; T8.5 deploys
to GitHub Pages; T4.5 runs in two passes, datagen then day mode; T5.3 `legal_hard` runs day pass → datagen weekend → offline `--pass build`, D246).
Round 12: no new task IDs; changes marked **R12** in `tasks/TASKS.md` (T4.1 assigns nightly blocks and the judged
subset; T1.10 adds `--split`/`--block`/`--judged-subset`; T6.1 owns refs `nightly-b<k>` and the block-restricted
release drift; T6.2b schedules the block rotation, the cron-string guard and the skip report; T1.3/T1.8 own the
retrieve test-matrix rows; T1.13 lists `test_client_auth.py`, which T3.4/T3.6 move; T8.1's derive script lives in
`scripts/dashboard/`; D248–D283).
Round 13: no new task IDs; changes marked **R13** in `tasks/TASKS.md` (T1.9 `post_status` + `labels.schema.json`; T1.10
`--stratum` and the counter-based `--block auto`; T1.2 creates the `core/config/` package; T4.1 `full` quota, `rq1`,
subset incl. injection; T1.8 judged-subset generation scope; T6.1 `release-b<k>` refs, whole-tree publish, sanitised
`infra_error`; T6.2a dispatch-only PR jobs and `post_status` call sites; T6.2b App-token `gate-router.yml`, guard
output, `state/nightly_counter`, release anchors; T7.2 true-effect reference; T7.3 `rq1`; T8.5 `demo-ready.yml`,
build-id smoke; T0.7 `demo-net` egress; D287–D323).
