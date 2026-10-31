# Review of the Prüfstand spec (v1, 27 Oct 2026)

Reviewer: Claude (planning pass; review rounds 1–13 in §8). This file records the verdict on the original spec
(`docs/spec/SPEC-v1-original.md`), what was missing, and every decision taken to fill the gaps.
The authoritative spec from now on is `docs/spec/SPEC.md` (v2).

## 1. Verdict

| Dimension | Score | Comment |
| --- | --- | --- |
| Idea / problem fit | 9/10 | Real, under-served problem (German RAG, regulated buyers, tenant leaks). Clear differentiators. |
| Research value | 9/10 | RQ3 mutation benchmark is a genuinely publishable, defensible result. |
| Product scope | 7/10 | Coherent, but too much for 5–7 weeks; dashboard + demo + paper + PyPI + Marketplace + HF is 3 projects. |
| Engineering plan | 5/10 | No CI/CD design, no test strategy, no data model, no security model for CI, no deployment plan. |
| Executability by an AI agent | 5/10 | Phases are too large for one session; interfaces between modules are not fixed, so separate sessions would invent incompatible APIs. |

**Bottom line:** the idea is strong and the research design is the best part. The plan is a good
*product* spec but not yet a *build* plan. v2 keeps every idea and fixes the build plan.

## 2. Critical gaps (would have broken the project)

1. **No GPU in GitHub-hosted CI.** The PR flow runs a 7–14B generator, BGE-M3, a reranker and an
   LLM judge inside a GitHub Action. On a free hosted runner (CPU, 4 vCPU) 350 cases × ~5 LLM calls
   would take hours, not 3 minutes. → (revised in round 4, §8) *Three CI tiers* (ADR-0005), all with **real models**: tier 0 code
   checks; tier 1 **live** on the hosted CPU runner (real rag-demo + small llama.cpp model + real
   embeddings on the 20-case `smoke_live` split of the 40-case fixture, a gate that decides on hard fails and
   `error_rate` only with everything else reported (round 9), informational GitHub Models judge, ≤ 20 min; round 8); tier 2 the full gate on the
   **A40 cluster** through a private executor repo, only for trusted PRs. No fake LLM, no fake target.
2. **Self-hosted runner on a public repo = remote code execution on your cluster.** Any fork PR could
   run code on the A40s. → (revised in rounds 1 and 2, §8) the runner is never attached to the public repo,
   and the public repo holds no gate secret except the App key `gate-router.yml` needs (round 13). A private
   executor repo runs a PR only when the owner dispatches it (round 13: no `run-gate` label), takes config, dataset
   and code from trusted `main`, and runs the
   signed candidate image without GPU or internet access. A fork PR is gated only after a maintainer
   reviews it and pushes it to a `gate/pr-N` mirror branch.
3. **Cache key would hide regressions.** `hash(question, tenant, config)` ignores app code changes:
   a PR that breaks retrieval code but keeps `rag.yaml` would be served stale (good) answers and
   pass. → target responses are keyed on a **target fingerprint** (image digest / git tree hash of
   the app + `rag.yaml` hash + corpus version); judge calls are cached separately (ADR-0006).
4. **Perturbed cases are not independent.** The bootstrap resamples cases, but 11 perturbations of
   one base question are strongly correlated → CIs far too narrow → false blocks. → **cluster
   bootstrap** with cluster = base question id (ADR-0007).
5. **Baseline validity.** A `main` baseline is only comparable if dataset version, judge model,
   judge prompt version and corpus version are identical. → baseline lookup by **evaluation
   fingerprint**; mismatch = re-run baseline, never compare across fingerprints.
6. **Indirect-injection docs must be inside the RAG index.** The spec plants attacks "inside
   documents" in the dataset builder, but the reference app indexes the corpus separately. → attack
   documents are a first-class corpus artefact produced by `attacks/` and ingested per tenant
   (dependency added to the task graph).
7. **No data model.** Runs, cases, metric values, baselines, LLM calls, cache: never defined, and two
   stores (DuckDB + Postgres) were proposed. → files are the source of truth (`run.json`,
   `results.parquet`), DuckDB is a local query index, **Postgres dropped** (ADR-0003). Full ERD in
   `docs/architecture/data-model.md`.
8. **Fixed interfaces missing.** With separate AI sessions per phase, each session would invent its own
   `TestCase`/`RunResult`. → `docs/architecture/interfaces.md` fixes the cross-module contracts
   before any code; `import-linter` enforces the layering in CI.

## 3. Important gaps

| # | Gap | Fix in v2 |
| --- | --- | --- |
| 9 | Phase order puts dataset publishing + human labeling before the gate works ("ship Phase 4 end-to-end" contradicts the order) | New **Phase 1 = real thin slice** (round 4): real 5-law corpus slice + real rag-demo v0 (llama.cpp on CPU) + deterministic metrics + gate + PR comment + Action, end-to-end in tier-1 CI with real models |
| 10 | Citation regex only handles `§`; EU acts (GDPR, NIS2, AI Act) cite **Art./Artikel**, plus `§§ 622 ff.`, `Abs. 2 S. 1`, `i.V.m.`, English "Article 6 GDPR" | Citation parser with normaliser + table-driven tests (T1.5a) |
| 11 | Decision rule details: one- vs two-sided, how Holm gets p-values from a bootstrap, small slices | Defined exactly in SPEC §7.2 + ADR-0007; min slice n = 30 else `insufficient_data` (report-only) |
| 12 | No simulation test proving the gate's false-alarm rate | Monte-Carlo test in the test suite: under H0 the fail rate must be ≤ α (+ tolerance) |
| 13 | Dataset licensing: mixing ODbL (OLDP), CC BY (GermanQuAD/DPR: CC BY 4.0 per their HF cards, checked in round 4; GermanRAG verified in T2.1) and own data in one HF dataset | License-homogeneous HF **configs** (`laws_eurlex` CC BY 4.0, `germanquad_derived` CC BY 4.0 unless T2.1 finds otherwise, `oldp_derived` ODbL); MEMERAG (CC BY-NC) is download-only |
| 14 | Target contract undefined for third-party systems that don't return chunks or tenant ids | Versioned target API (OpenAPI); metrics declare required fields; missing fields → metric `not_applicable`, never silently 0 |
| 15 | Timeline 5–7 weeks is unrealistic (human labeling 200–300 pairs + reviewing 300+ generated items alone ≈ 1 week) | Re-estimated in round 2: **20–26 weeks** part-time (≈ 230 AI-session hours + ≈ 55 human hours); skeleton gate green in CI at ~week 5, MVP (gate on the real app) at ~week 12–14; optional scope marked in TASKS |
| 16 | Human labels need fluent German | Answered in round 4: no annotator; calibration from existing human-annotated data (MEMERAG-DE, GermanQuAD, GermanRAG), see §6 Q1 |
| 17 | No CI/CD, release, security scanning, dependency policy, branch protection | `docs/engineering/*` + T0.2, T9.1a |
| 18 | No test strategy (only "unit tests") | Test pyramid in `docs/engineering/testing-strategy.md`: unit, property (Hypothesis), contract, integration (Testcontainers/Qdrant), e2e on the real stack (round 4: no fakes), statistical validation of the gate maths, UI (Playwright + visual + axe), GPU smoke |
| 19 | No observability | structlog JSON logs, OpenTelemetry spans, every LLM call in `llm_calls` table |
| 20 | Demo "try it" page is a public LLM endpoint: cost abuse + injection target | Hard budget cap, per-IP rate limit, Turnstile-free design (no CAPTCHA reliance), fixed tenant set, no write paths |
| 21 | Model names in config (`ollama/qwen-small`) are placeholders; judge-≠-generator-family rule is not enforced | Config validator rejects judge family == generator family (T1.2); model selection task on A40s (T3.1b) |
| 22 | The RAG app could accidentally see test data | `apps/rag-demo` must not import `pruefstand`; CI check that no dataset files are under app paths |
| 23 | Budget limit meaningless for local models (cost = 0) | Track GPU-seconds + tokens; budget can be USD or tokens |
| 24 | Laws change; gold answers stale | `law_version_date` per chunk + `corpus_version` in every fingerprint |

## 4. Nice-to-have additions (accepted)

- `mkdocs-material` docs site built in CI with `--strict` (broken links fail CI); all diagrams in Mermaid so GitHub renders them.
- Generated module dependency graph (`pydeps`) rendered by CI into the docs site (`docs/architecture/generated/` holds only a README).
- Code-level mutation testing (`mutmut`) on `gate/` and `metrics/` nightly – the gate must itself be well tested.
- JSON Schemas generated from Pydantic → TypeScript types for the dashboard (contract test, no drift).
- Release automation: Conventional Commits + release-please, PyPI Trusted Publishing, GHCR images signed with cosign + SBOM.
- Second-opinion code review on every PR from a different model family via **GitHub Models** (`gh models run`, available with a GitHub account). Copilot code review is optional; it is not part of GitHub Pro.

## 5. Decisions taken (no questions needed)

All recorded as ADRs in `docs/adr/` and summarised in `docs/decisions.md`.

| ADR | Decision |
| --- | --- |
| 0001 | Monorepo: `uv` workspace (Python 3.12) + `pnpm` for the dashboard; `src/` layout |
| 0002 | Walking-skeleton-first phase order |
| 0003 | Files are source of truth; DuckDB index; no Postgres |
| 0004 | Baselines keyed by evaluation fingerprint in a plain-file `baselines` branch of the private executor repo; pluggable store (local dir / git branch) — *revised in rounds 1–2* |
| 0005 | Two-tier CI: hosted runners for code; A40 runner only in the private executor repo, dispatched for trusted PRs — *revised in round 1* |
| 0006 | Two caches: target responses (target fingerprint) and judge calls (judge fingerprint) |
| 0007 | Paired **cluster** bootstrap; FAIL = significant and relevant drop on gated slices; one Holm family per run; min 30 clusters — *revised in rounds 1–2* |
| 0008 | Real-stack testing (round 4): no FakeLLM / FakeTarget; real rag-demo with bug switches, cassettes recorded from real calls |
| 0009 | All LLM calls through LiteLLM; **free providers only** (round 4): local vLLM (A40s; round 10: Ollama via the VM tunnels, round 11: native API only, D219), llama.cpp (CPU), GitHub Models free tier; opt-in free tiers; paid blocked |
| 0010 | Qdrant only, dense + own German sparse vectors in one collection, tenant filter inside the query, RRF fusion |
| 0011 | Dashboard = Next.js static export reading run artefacts; Playwright for UI tests |
| 0012 | Demo hosting separate from the GPU cluster (small CPU host + CPU llama.cpp, D92) |
| 0013 | Observability: structlog + OpenTelemetry |
| 0014 | Typed config (Pydantic) for `pruefstand.yaml` and `rag.yaml`, JSON Schema published |
| 0015 | Dataset split into license-homogeneous configs |
| 0016 | Architecture enforced with `import-linter` layered contracts |
| 0017 | Release: release-please, PyPI Trusted Publishing, cosign-signed GHCR images, SBOM |

## 6. Open questions / resources needed from you

Owner answers recorded on 2026-10-28 (round 4).

| # | Question | Default if no answer |
| --- | --- | --- |
| Q1 | Is a German speaker available for judge labels and the 20 % review? | **Answer: not known → none assumed.** Judge calibration uses existing human data (D88): MEMERAG German subset (expert faithfulness labels, CC BY-NC 4.0, download-only), GermanQuAD 3-way answers (constructed correctness pairs), GermanRAG (refusal). The 20 % dataset review becomes a cross-family model review + owner spot-check of 50 items with a translation aid (documented limitation). Optional T5.3-opt if a German speaker turns up. |
| Q2 | How is the A40 cluster accessed? | **Answer: plain SSH** (no Slurm). T0.6 (week 1) checks user-level services, Docker / rootless Docker / Podman / Apptainer, GPU access, outbound HTTPS and whether a runner may run; go/no-go, fallback = one rented 48 GB GPU (D90). |
| Q3 | Budget for paid APIs? | **Answer: free only** (D86). Local vLLM on the A40s (round 10: Ollama, D198), llama.cpp on CPU in CI, GitHub Models free tier; opt-in free tiers (Mistral, Gemini, Groq, OpenRouter `:free`); paid providers blocked by `LLMPolicy`; private docs and canaries never go to an external API. |
| Q4 | GitHub repo name/owner and Hugging Face username? | **Owner will provide.** Placeholders `dheena18`, `<HF_USER>` stay until then. |
| Q5 | Demo hosting account? | **Answered round 11 (D235, D239):** dashboard on **GitHub Pages** (free, CSP via hash-based `<meta>`); optional demo API on the VM behind a free **Cloudflare Tunnel**. Vercel, Fly.io and Hetzner are dropped. |

## 7. What is in this planning pack

```text
REVIEW.md                  this file
CLAUDE.md                  ground rules, auto-loaded by Claude Code in every session
docs/spec/SPEC.md          spec v2 (authoritative); SPEC-v1-original.md kept for reference
docs/decisions.md          decisions log (short, paste at session start)
docs/adr/                  one ADR per decision
docs/architecture/         diagrams (Mermaid): context, containers, components, call graph,
                           sequences, data model/ERD, deployment, CI/CD; interfaces.md = contracts
docs/engineering/          coding standards, testing strategy + harnesses, CI/CD, Docker,
                           git workflow, security, GPU cluster, AI workflow
tasks/TASKS.md             epics → tasks → subtasks, dependencies, estimates
prompts/                   one ready-to-paste prompt per task + session/review templates
```

No application code has been written. Code starts after you approve the prompts.

## 8. Review rounds

### Round 1 (2026-10-28)

Three independent reviewers (consistency, technical soundness, AI executability) read the whole pack.
Findings and resolutions are kept as history in `docs/planning/reviews/`; the binding record is
`docs/decisions.md` (D22–D50).

| Reviewer | Blocker | Major | Minor |
| --- | --- | --- | --- |
| Cross-document consistency | 4 | 33 | 23 |
| Technical soundness | 9 | 27 | 14 |
| AI executability | 10 | 40 | 20 |

The main redesigns:

1. **Gate decision rule.** The v2 rule ("fail only if a drop larger than δ is proven") almost never
   failed a real drop of δ (power ≤ 2.5 % at Δ = δ, 19–55 % at 2δ for realistic noise), and requiring
   every slice to pass made WARN appear on nearly every no-op PR. New rule: FAIL = Holm-adjusted
   one-sided p (H0: no drop) < 0.025 **and** mean drop > δ, on gated slices only (overall, tenant,
   lang; perturbation for retrieval metrics). Other slices are informational. Clusters = source
   document. Errors count as worst value. Absolute limits use Wilson bounds. Every PR comment shows
   the minimum detectable effect, and the simulation tests now check type-I error, power at 2δ and
   the no-op WARN rate.
2. **Private gate executor.** Gating a self-hosted runner with `if:` conditions in workflow files
   does not stop a fork PR, because the fork controls those files. The A40 runner now belongs only
   to a private repo `pruefstand-gate`. The public repo dispatches trusted SHAs to it. Images are
   built on hosted runners, signed, and pulled by digest. (Round 11: the dedicated VM uses rootful Docker with a
   single service user `pruefstand`, D211–D213.)
   Baselines, held-out canaries and full artefacts stay private; public PR comments are redacted.
3. **Judges.** One scale per metric (3-point for faithfulness/correctness, binary for the rest),
   weighted κ with CIs, a second annotator for a human ceiling, and the family rule checked against
   the target's real generator at run time.
4. **Serving reality.** A single GPU allocation plan, a model catalogue that PRs must use, PR-scoped
   Qdrant collections, realistic budgets (PR tier ≤ 25 min, nightly ≤ 4 h), and the serving stack in
   the target fingerprint.
5. **Executability.** New human task T0.0 (WSL2, tools, repo). One definition of Make targets.
   Fixed dependency order, a new `ROBUST_PR` split, a synthetic fixture generator so e2e tests can
   produce a FAIL, and `[GPU]/[NET]/[DOCKER]/[HUMAN]` tags. Eight oversized tasks are split into
   a/b prompts (72 prompts in total).

### Round 2 (2026-10-28)

Two new reviewers: a verifier (every round-1 blocker/major re-checked, then a fresh consistency
sweep) and a principal engineer who had not seen round 1. Binding record: `docs/decisions.md`
D51–D79.

| Reviewer | Result |
| --- | --- |
| Verifier, round-1 items | 126 blocker/major items: 111 resolved, 15 partly, 0 open, 0 regressed |
| Verifier, new issues | 2 blocker, 13 major, 25 minor |
| Principal engineer | 3 blocker, 25 major, 12 minor + top-10 risk list |

The main changes:

1. **One Holm family per run.** With one family per metric, a no-op PR still failed 6–20 % of the
   time across 8 gated metrics. Now all (gated metric × gated slice) pairs form one family: no-op
   false-block ≈ 2–4 %, power at 2δ stays 0.97–1.00. Informational slices are always PASS (only
   flagged "notable"). Robustness is gated through one `perturbed_all` slice over a 40-base
   `ROBUST_PR` split. MDE has a δ floor. likely_cause returns string codes.
2. **Simpler, safer CI for one person.** No secrets and no dispatch workflow in the public repo: the
   private executor runs PRs (round 8: label poll; since R13 D288 only an owner `workflow_dispatch`), takes config, dataset and code from trusted
   `main`, and runs the candidate image without GPU or internet. One GitHub App posts the
   `pruefstand/gate` status. Baselines are plain files in the private repo (no signing). Branch
   protection needs 0 approvals; the second-family reviewer is GitHub Models, Copilot is optional.
3. **Bootstrap that works on Windows.** WSL2 with the repo in the Linux filesystem, LF line
   endings, gh over HTTPS, exact tool install and verify steps, pytest import mode, and T0.1 lands
   on `main` by direct push before protection exists.
4. **Contracts.** Fingerprint signatures, one model-family table, `ConfigError` for family
   violations, `DiskKVCache` in T1.8, `CanaryRegistry` in core, `MetricPolicy.confidence`.
   Prompts no longer reference review files.
5. **Scope and risk.** Realistic timeline **20–26 weeks part-time**, MVP around week 12–14. TASKS has
   a Tier column; optional: try-it page, Marketplace repo, Phase 10 (the nightly 70B judge tier was dropped in the round-8 integration: the nightly judge is `gemma` on one A40, D141). The top
   risk (unknown A40 access) gets its own task **T0.6** in week 1 with a go/no-go and a rented-GPU
   fallback.

### Round 4 (2026-10-28): owner answers and "real models, real CI"

The owner answered Q1–Q5 (§6) and asked for **no fake LLM and no fake target, real LLMs and real CI
in GitHub**. Binding record: `docs/decisions.md` D80–D90; ADR-0008 is now "Real-stack testing".

1. **No fakes.** FakeLLM, FakeTarget and degradations are removed. Unit tests use real inputs; the
   gate statistics are validated on simulated numbers (that tests maths, not the product); fast
   `llm/` parser tests replay cassettes recorded from real calls, and every such behaviour also has
   a live test.
2. **Real CI on GitHub.** New tier 1 `live-e2e.yml` on the hosted runner: real Qdrant, real
   rag-demo, a real German-capable llama.cpp model, real embeddings on a real 5-law slice, a real
   GitHub Models judge (free, `models: read`), a real gate against the main baseline and a real PR
   comment, on every same-repo PR. Failures are shown with real bug switches in `rag.yaml`
   (`tenant_filter: post_topk` etc.). M1 is now "tier 1 green on a real PR".
3. **New task T1.13** builds rag-demo v0 early (T2.1/T2.2 move into the early lane); T3.x extend it.
4. **Calibration without an annotator** (T5.3 rewritten): MEMERAG-DE, GermanQuAD, GermanRAG.
5. **Free providers only**, enforced in `LLMPolicy`; 429s from GitHub Models fall back to a CPU judge
   and are flagged in the run, never silent. (Superseded in round 8: no CPU judge; 429 → `judge_mode=skipped`, D97.)
6. **Licence fix:** GermanQuAD and GermanDPR are CC BY 4.0 on their HF cards (not CC BY-SA).

### Round 8 (2026-10-31): cold read 4, four lenses

Four reviewers read the pack cold (developer, AI/ML, UI, architecture/DevOps). Findings are in
`docs/planning/reviews/round8-{dev,ai,ui,arch}.md`; the binding resolution is `round8-resolution.md`
(W1–W5), recorded as `docs/decisions.md` D94–D140; the round-8 integration added D141–D145 (gemma nightly judge, refusal δ 0.10, single tier-1 judge cap, CPU-slice reviewer, executor ops).

| Reviewer | Blocker | Major | Minor |
| --- | --- | --- | --- |
| Senior developer | 2 | 9 | 19 |
| AI / ML engineer | 2 | 18 | 18 |
| UI designer + frontend | 3 | 16 | 9 |
| Architecture + DevOps/security | 2 | 22 | 30 |

The main changes:

1. **Tier 1 that fits (W1).** New 20-case split `smoke_live`; ≤ 2B generator with Qwen3 thinking off,
   `top_k 4`, no reranker, ≤ 20 min. The tier-1 gate decides on deterministic checks only (narrowed in round 9 to
   hard fails + `error_rate`); judged metrics are
   informational (≤ 10 cases per PR, `judge_mode=skipped` when the quota is gone, no CPU judge). The bug-switch
   matrix runs nightly and on rag-demo PRs; statistical scenarios move to tier 2.
2. **Executor operations (W2).** Persistent runner with cleanup hooks, per-workflow concurrency plus a GPU
   `flock`, `state/processed.jsonl`, no baseline → `failure`, fork PRs via `gate/pr-N`, public GHCR image, a
   separate public dashboard-data repo, heartbeat + health issue, backups and retention.
3. **Models and judges (W3).** A fixed family plan; judge cache key over all rendered inputs plus the provider's
   model version; nightly drift anchors; hard-negative calibration; per-metric ≥ 30 applicable clusters; refusal
   decided by the gate.
4. **Code quality (W4).** One ruff config (max-args 8, positional ≤ 5), doctests and script tests actually run,
   one coverage definition (CLAUDE.md §6), reduced PR simulation grid, and a maintained
   `docs/engineering/test-matrix.md` (the 7 untested symbols now have owners and tests).
5. **UI (W5).** `docs/design/ui-spec.md` is the UI source of truth; contracts gain δ/limit fields, a run index,
   per-case fields and sharded case files; de/en i18n; JSON error bodies for Try-it.

### Round 9 (2026-10-31): cold read 5, four lenses

Four reviewers read the pack cold again (developer, AI/ML, UI, architecture/DevOps). Findings are in
`docs/planning/reviews/round9-{dev,ai,ui,arch}.md`; the binding resolution is `round9-resolution.md` (X1–X5),
recorded as `docs/decisions.md` D146–D188, plus D189–D195 for reviewer fixes adopted where the resolution is silent.

| Reviewer | Blocker | Major | Minor |
| --- | --- | --- | --- |
| Senior developer | 3 | 15 | 21 |
| AI / ML engineer | 1 | 12 | 13 |
| UI designer + frontend | 1 | 8 | 16 |
| Architecture + DevOps/security | 0 | 13 | 22 |

The main changes:

1. **Blockers (X1).** The judge pass rule no longer computes κ on the all-negative hard subset (it could never pass):
   κ ≥ 0.6 on the full set **and** specificity ≥ 0.80 on hard negatives (Wilson lower bound ≥ 0.70). One static
   dashboard build per fixture set with build-time schema validation. A raw-data guard allowlist so tasks that must
   commit result parquet files can pass `make check`. Two tier-1 baseline artefacts (`live-baseline`,
   `live-baseline-nightly`) so a nightly run never breaks the PR fingerprint. Test-only configs may lower
   `min_clusters`; committed configs may not.
2. **CI, executor, security (X2).** The orchestrator holds the GPU lock once per job (no re-entrant `flock`
   deadlock; T3.1a builds the three GPU scripts); `gate-router.yml` is the single, checkout-free
   `pull_request_target` workflow so docs-only PRs never wait for the A40 runner; fork gating bound to the head SHA
   recorded at dispatch time (R13 D288); images built from the PR head SHA; held-out registry unreachable from the candidate;
   whole backups encrypted; baseline files on the cluster disk with only `index.json` in git; pre-deploy leak
   probes; `uv.lock` committed to release PRs.
3. **Evaluation (X3).** `legal_hard` in T5.3; owners for `citation_grounded`, `system_prompt_similarity`
   (T1.5b) and `evidence_recall` (T7.3); judge serving + `judge_epoch` in `eval_fingerprint` while drift only
   invalidates the cache; 50 drift anchors with a confidence bound; σ_d measured with regeneration; perturbed cases
   only in `perturbed_all`; `core` = 220 answerable + 50 unanswerable + 30 probes with `false_refusal` gated in PR
   runs; static `/v1/info.serving`; `RetrievedChunk.used_in_prompt`; tier-2 config `rag.gpu.yaml`.
4. **Code quality (X4).** An explicit "allowed long signatures" table with inline `noqa`; one `pythonpath` /
   `mypy_path` list; `Budget.reserve()` / `release()` so the request cap cannot race into `BudgetExceeded`; one
   `set_check` mapping table incl. `no_baseline`; `test-matrix.md` rebuilt from interfaces.md and the prompts with
   honest statuses (`open` where a round-9 test row is still to be added by its task).
5. **UI (X5).** Locale routing and a static root redirect; a CSP without inline scripts (own CSP for
   `report.html`); typed `DashboardSliceRow` / `DashboardSlices` / `LabelsDocument`; one rule placing every
   `SliceDecision` in exactly one table; a defined no-baseline state (⚪, `baseline_run_id = None`,
   `RunIndexEntry.no_baseline`); tier 1 decides on hard fails and `error_rate` only, everything else is reported.

### Round 10 (2026-10-31): real cluster facts

No reviewer round: the owner supplied the real facts of the A40 cluster (`ollama list`, `nvidia-smi`, `df -h`,
`loginctl`) and later the same day confirmed the TrueNAS VM details. The binding resolution is
`docs/planning/reviews/round10-resolution.md` (Z1–Z7), recorded as `docs/decisions.md` D196–D210 (D204–D210 are
decisions accepted with it). The main changes:

1. **Topology.** The cluster `cairo-s101lp` has a full local disk, no confirmed Docker and `Linger=no`, so it runs
   **only two Ollama servers** (GPU0 generator + `bge-m3`, GPU1 judges; started with `setsid nohup` since round 11)
   with models on the NAS. Runner,
   orchestrator, Docker, Qdrant, candidates, the CPU reranker, locks and state move to the TrueNAS VM
   `pruefstand-exec` (64 GB RAM), which reaches Ollama through `autossh` tunnels and logs in with an SSH key only.
2. **Serving.** vLLM and TEI leave the default plan; provider `ollama` replaces `hosted_vllm`; the existing
   `qwen3.8:27b-q8_0` is the provisional generator (family and licence verified in T0.6/T3.1b), `num_ctx` 8192;
   the gemma nightly judge runs on GPU1 and may overlap generation; the reranker runs on the VM CPU.
3. **Isolation.** A new trusted `llm-proxy` (T6.2a) is the candidate's only route to Ollama, because Ollama has no
   API key: it allows only chat/embed calls for the run's catalogue tags and blocks pull/delete/`keep_alive`.
4. **Storage.** One NAS dataset seen by both machines (`/data/dheena/truenas-ollama` ↔ `/mnt/pruefstand`) holds
   models, cluster scripts, data, baselines and backups; locks and databases stay on the VM disk.
5. **Tasks and workflow.** T0.6 becomes a facts check; new **T0.7** (VM setup) gates T3.1a and T6.2a; T3.1a/T3.1b
   are rewritten for Ollama. The VM is the primary development machine (VS Code Remote-SSH; WSL2 optional), and
   `tasks/PARALLEL-PLAN.md` schedules the build in waves of up to 6 agents (≈ 12–15 weeks part-time instead of
   20–26 serial).

### Round 11 (2026-10-31): cold read 6

Four cold reads (`round11-{dev,ai,ui,arch}.md`: 2 blockers, 33 majors, 47 minors in total) against the round-10
plan. The binding resolution is `docs/planning/reviews/round11-resolution.md` (Y1–Y7), recorded as
`docs/decisions.md` D211–D247 (D242–D247: round-11 integration: `llm-proxy` on `gate-net` + `proxy-egress`, Pages layout, demo-ready + nightly `demo-deploy`, `infra_error: str | None`, `legal_hard` order + `is_drift(a0=)`, rerank port / exit 15 / cluster wrapper / ports). The main changes:

1. **One identity on the VM (Y1).** System user `pruefstand` owns runner, orchestrator, cluster key
   (`/home/pruefstand/.ssh/id_ed25519_cluster`), the system unit `pruefstand-tunnel.service`, state and the lock
   `/var/lib/pruefstand/gpu.lock`; owner and agents share that lock through `pruefstand-lock`; `MAINTENANCE` is a
   file in the same directory. Docker is rootful; agents are root-equivalent on this dedicated VM (accepted risk)
   and never touch `/var/lib/pruefstand/**` or `/home/pruefstand/**`. The dev stack uses `PORT_OFFSET=10000`;
   `llm-proxy` is a normal container on `gate-net` + `proxy-egress`, reached as `http://llm-proxy:11500`; the tunnel also binds `172.17.0.1`, firewalled to `proxy-egress` (D242).
2. **Auth and API (Y2).** rag-demo sends `Authorization: Bearer $PRUEFSTAND_CANDIDATE_API_KEY` to `llm-proxy`
   (T3.4, T3.6; T1.13 from day 1); `rerank-cpu` has no auth; new endpoint `POST /v1/retrieve` (T3.5).
3. **Ollama correctness (Y3).** Native `/api/chat` and `/api/embed` only (LiteLLM `ollama_chat`), fixed per-model
   `options` in the catalogue (the proxy overwrites client options), one id format `ollama/<tag>`.
4. **Budgets (Y4).** `robust_pr` is retrieval-only; reranker top 10 at 256 tokens; night window 22:00–06:00
   Europe/Berlin (≤ 8 h) with a rotating 600-case nightly subset of `full`; cause-switches weekly; any judge
   fallback makes judged metrics informational.
5. **Unattended operation (Y5).** Heartbeat every 15 min during jobs; infra failures post `error` (not `failure`)
   and retry once; NAS automount unit and VM autostart; `setsid nohup` instead of `tmux`; mandatory weekly laptop
   backup with a receipt checked after 8 days.
6. **Developer and UI fixes (Y6, Y7).** Test matrix refreshed (259 rows); datagen sets `MAINTENANCE` itself;
   `cluster.env` rendered by T3.1a; mypy roots for `infra/vm`, `infra/cluster`, `infra/gate-executor/*`; worktrees
   get `.env`; dashboard on GitHub Pages with `<meta>` CSP; empty-set placeholder param; fixtures derived from real
   tier-1 runs; renderers accept a missing baseline; demo on the VM behind a Cloudflare Tunnel.

### Round 12 (2026-10-31): cold read 7

Four cold reads (`round12-{dev,ai,ui,arch}.md`: 1 blocker, 19 majors, 43 minors in total) against the round-11
plan. The binding resolution is `docs/planning/reviews/round12-resolution.md` (N1–N7), recorded as
`docs/decisions.md` D248–D283 (D271–D283: the reviewers' minors where N is silent; where two minor fixes conflicted
the row names the choice: `rerank.on_retrieve` (DEV12-09) instead of a request field (AI12-07),
`LabelsDocument.hard_fail_rules: dict[str, str]` for UI12-15). The main changes:

1. **Nightly rotation and judged subset as contracts (N1, the blocker).** `TestCase.block` (0/1/2; `None` for the
   refusal stratum, which runs every night) and `TestCase.judged_subset` (fixed seeded 150 `core` cases) are assigned
   by T4.1 and recorded in `DatasetManifest`; `pruefstand run --split full --block auto|0|1|2` and `--judged-subset`
   (T1.10); `RunManifest.block` / `.judged_subset` enter `eval_fingerprint`; nightly gates against ref
   `nightly-b<k>`, PRs against `main`, drift against `release` restricted to the block (T6.1, T6.2b).
2. **`llm-proxy` option policy (N2).** The proxy enforces only the allow-list, `num_ctx` and `keep_alive`; sampling
   options pass through within catalogue bounds, so mutation M17 and the noise-study churn arms measure what they
   claim. `GET /health` → `{model_reloads, upstream_errors, requests}`, differences land in `RunManifest.counts`.
3. **Drift rule (N3).** Changed anchor verdicts ≥ `max(3, ceil(0.1·n))` for hosted and local judges.
4. **Ops (N4).** Tunnel independent of the NAS mount, runner `Wants=`/`After=` the automount; firewall in
   `DOCKER-USER` + `PRUEFSTAND-INPUT` (from `INPUT`) via `pruefstand-firewall.service`; nightly stops gracefully before 06:00 (`window_exceeded`) and a
   skipped nightly is reported; agents on the VM hold only a public-repo fine-grained token; `docs.yml` concurrency
   fixed.
5. **UI (N5).** Published-site size cap; `docs.yml` triggered by `workflow_run`; demo deployed by public image
   digest; Try-it reset endpoint for tests; a required `basePath` PR check.
6. **Developer fixes (N6, N7).** Prompts' Interfaces blocks carry the R11 signatures; `test_client_auth.py` has an
   owner and porters; tests per root in `<root>/tests/` with `make typecheck` per root; derive script in
   `scripts/dashboard/`; test matrix per DEV12-07 plus R12 rows (271 rows); judge `num_ctx` 12288.

### Round 13 (2026-10-31): cold read 8

Four cold reads (`round13-{dev,ai,ui,arch}.md`: 0 blockers, 15 majors, 47 minors in total) against the round-12
plan. The binding resolution is `docs/planning/reviews/round13-resolution.md` (P1–P5), recorded as
`docs/decisions.md` D287–D323 (D319–D323: round-13 integration; D305–D318: the reviewers' minors where P is silent; where two fixes conflicted the
row names the choice: per-block release anchors `release-b<k>` written by the release run of all of `full`, retried until promoted (AI13-09 + A13-M5, D321),
judged subset **with** injection (AI13-11 rejected), test reset via `docker compose exec` instead of a token
(UI13-04), late start = `aborted: window_exceeded`). The main changes:

1. **Gate trigger and required status (P1, security).** `gate-router.yml` posts `pruefstand/gate` with the
   `pruefstand-bot` App token from environment `gate-router`; the ruleset pins the status to that App, so a branch
   workflow cannot satisfy it. Tier 2 for a PR starts only by the owner's `workflow_dispatch` of the private
   `gate-executor.yml`; the `run-gate` label is gone. CLAUDE.md rule 9, secrets.md and security C18 state exactly
   what the VM token can do.
2. **Nightly guard and demo isolation (P2).** The guard's `run` output gates the nightly job; a late start ends at
   once with `window_exceeded`; `demo-net` cannot reach the LAN.
3. **Data composition (P3).** `full` has a fixed quota (refusal ≈ 150 + 3 × 450 per block); RQ1 gets its own
   offline split `rq1` (`Split.RQ1`); RQ3 detection counts only mutations whose measured true effect ≥ δ; the PR
   fallback subset limits generation **and** judging of `core` answerable cases.
4. **Contracts (P4).** test-matrix statuses `covered`/`planned`/`weak`, one owner per row (342 rows);
   `GitHubPublisher.post_status`; `pruefstand run --stratum all|refusal|blocks`; block rotation by the persisted
   `state/nightly_counter`.
5. **UI / deploy (P5).** `push_dashboard_data` rewrites the whole published tree (200 / 20); `demo-ready.yml` with
   `actions: read` on `fetch-artefacts` only, `deploy.yml` dashboard-only; one anonymous `releases/latest` call per
   night; Try-it reset from inside the container; Pages `build-id.txt` polled by the post-deploy smoke.
6. **Minors.** Judge context rule 12 288 = 8 192 + 3 072 + 1 024; generator tokenizer + `prompt_overflow`;
   per-judge drift threshold; `judge-drift` before the nightly gate; compose rule (`make ports-env`); heartbeat
   vocabulary + `maintenance`; `core/config/` package; `labels.schema.json` owned by T1.9; new env rows.
