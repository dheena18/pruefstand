# Round 9 resolution — binding decisions (cold read 5)

Inputs: `round9-dev.md` (3/15/21), `round9-ai.md` (1/12/13), `round9-ui.md` (1/8/16), `round9-arch.md` (0/13/22).
Overrides earlier resolutions where they conflict. Where silent, apply the reviewer's exact fix.

## X1 Blockers

| # | Decision |
| --- | --- |
| X1.1 | (AI9-01) Judge pass rule: κ ≥ 0.6 on the full calibration set **and specificity (true-negative rate) ≥ 0.80 on the hard-negative subset, with the 95 % Wilson lower bound ≥ 0.70**. κ is never computed on a single-label subset. |
| X1.2 | (UI9-01) One static dashboard build **per fixture set**: `apps/dashboard/fixtures/{populated,empty}/`, each built and tested as its own Playwright project. Data is schema-validated at build time; invalid data fails the build in CI before deploy, so the static site has no "bad data" panel. The error state is tested via the 404 page. Loading states may use `page.route` **only to delay** real fixture responses (never to change data). |
| X1.3 | (dev T2.1) The raw-data guard has an allowlist: `results/**`, `experiments/**/results/**`, `apps/dashboard/fixtures/**`, `datasets/fixtures/**`, `tests/**/fixtures/**`. |
| X1.4 | (dev T1.12) Two tier-1 baseline artefacts: `live-baseline` (written only by push-to-main runs of the 20-case `smoke_live` PR shape) and `live-baseline-nightly` (nightly 40-case runs). PRs compare only to `live-baseline`. |
| X1.5 | (dev T1.10) Test-only configs live in `packages/pruefstand/tests/fixtures/configs/` and may lower `min_clusters`; the committed-config rule (`min_clusters ≥ 30`) applies to `examples/**` and `apps/**/configs/**` only. |

## X2 CI / executor / security (arch majors)

| # | Decision |
| --- | --- |
| X2.1 | Locking: the orchestrator takes `gpu.lock` once per job; `switch-mode.sh`, `health.sh` and `fetch-model.sh` never take the lock and refuse to run unless `PRUEFSTAND_LOCK_HELD=1`. Preflight runs **after** taking the lock (fix both diagrams). These three scripts are created by **T3.1a**. |
| X2.2 | Required check for non-gated PRs: a public `gate-router.yml` on `pull_request_target` with **no checkout** and permissions `statuses: write, pull-requests: read` only; it reads the changed-file list from the API and posts `pruefstand/gate` = success "not gated" when no gated path changed. This is the **only** allowed `pull_request_target` workflow (documented exception; the workflow guard in T0.2 allowlists exactly this file and asserts it has no checkout step). Gated PRs get `pruefstand/gate` from the executor App. The ruleset requires the context without pinning the source app. |
| X2.3 | Fork PRs: when the maintainer labels, the executor records the fork PR head SHA from the label event; it gates `gate/pr-N` only if its head SHA equals that recorded SHA, and posts the status to that SHA only. |
| X2.4 | `build-images.yml` builds from `github.event.pull_request.head.sha` (not the merge commit). |
| X2.5 | Held-out canary **registry** is never mounted into or reachable by the candidate container; the candidate sees only the corpus through Qdrant over the internal network. |
| X2.6 | Backups: the whole weekly bundle is `age`-encrypted (not only the canaries); the key lives only on the owner's laptop. |
| X2.7 | Baselines live on the cluster disk under `$PRUEFSTAND_HOME/baselines/<fp>/history/<run_id>/` (last 20 kept) and in the encrypted weekly backup; the private repo's `baselines` branch keeps only a small `index.json`. This ends repo growth. |
| X2.8 | T8.5 adds a pre-deploy job that runs the leak probes against the deployed-candidate demo API and blocks deploy on any leak. |
| X2.9 | release-please PRs: `release-please.yml` runs `uv lock` after the version bump and commits `uv.lock` to the release PR. |
| X2.10 | Fix the stale `nightly_run` dispatch text in interfaces.md to the current executor inputs. |

## X3 Eval / models (AI majors)

| # | Decision |
| --- | --- |
| X3.1 | `legal_hard` calibration set is built in **T5.3** (in-domain hard negatives on the law corpus). |
| X3.2 | New metrics get owners and interface entries: `citation_grounded` and `system_prompt_similarity` in **T1.5b**; `evidence_recall` in **T7.3** (and listed in interfaces §5). |
| X3.3 | `eval_fingerprint` includes judge serving version (engine + version + quantization) and a `judge_epoch` integer. Drift **does not** change the fingerprint; it only invalidates the judge cache and marks judged metrics informational until re-calibration bumps `judge_epoch`. |
| X3.4 | Drift anchors: 50 items; drift = agreement < 0.85 **and** the 95 % lower bound < 0.80. |
| X3.5 | σ_d (T6.3) measured on no-op changes **with regeneration** (different sampling seeds, rebuilt index), i.e. real answer churn. |
| X3.6 | `robust_pr` perturbed cases count only in the `perturbed_all` slice; `overall`, `tenant` and `lang` use unperturbed cases. Recompute the MDE table. |
| X3.7 | `core` = 300 cases: 220 answerable, 50 unanswerable, 30 security probes. `false_refusal` (applies to answerable) is gated in PR runs; `refusal_correct` stays nightly-only (D-row from round 8). |
| X3.8 | The PR judge (mistral) never writes or rewrites references. `core` review/rewrites use the night gemma judge as a batch job. |
| X3.9 | Judge input cap = judge context window minus 1 024 tokens; truncation is logged per case and counted in the run; cases truncated are listed in the report. |
| X3.10 | RQ3: each mutation is scored only in the tier whose split can detect it (M06, M14, M15, M20 → tier 2 core/nightly). |
| X3.11 | Tier-1 injection: reported, **not** gating (n = 2). Injection gating happens in tier 2 (≥ 30 injection cases, Wilson rule). |
| X3.12 | Datagen (llama 70B) runs as manual weekend jobs (`datagen` mode), outside the nightly window. |
| X3.13 | `/v1/info.serving` holds only static fields (engine, engine_version, quantization, gpu model, model file sha256); runtime counters go to `/v1/health`. |
| X3.14 | `RetrievedChunk` gains optional `used_in_prompt: bool | None` (API v1, backward compatible); the faithfulness judge uses exactly the chunks with `used_in_prompt=true` (fallback: first `top_k`). |
| X3.15 | Tier 2 uses `apps/rag-demo/configs/rag.gpu.yaml`; T6.5's reranker demo edits that file. |

## X4 Code quality (dev majors)

| # | Decision |
| --- | --- |
| X4.1 | Signatures fixed by interfaces.md that exceed `max-args` carry `# noqa: PLR0913` and are listed in coding-standards.md §1.1 "allowed long signatures" (Runner.__init__, cluster_bootstrap_ci, CassetteRecorder, labels_document, decide, eval_fingerprint, …). |
| X4.2 | One `pythonpath` and `mypy_path` list in T0.1 (and CLAUDE.md §3) covering `packages/*/src`, `apps/rag-demo/src`, `scripts`, `data`, `experiments`, `tools`, `action`. |
| X4.3 | Coverage: as CLAUDE.md §6; T0.1 implements exactly that. |
| X4.4 | The deleted-module grep in T3.x checks only the specific deleted module paths, not package prefixes. |
| X4.5 | `Budget` reserves a request under an `asyncio.Lock` before the call (`reserve()` / `release()`); no race into `BudgetExceeded` at the cap. |
| X4.6 | `set_check` maps `GateReport.no_baseline=True` to commit status `failure` with the no-baseline message (single mapping table in interfaces §10). |
| X4.7 | test-matrix.md is refreshed against interfaces.md: every symbol row, correct test file names, statuses re-derived from the prompts. |

## X5 UI (UI majors)

| # | Decision |
| --- | --- |
| X5.1 | Next.js routing: `app/[locale]/layout.tsx` + `generateStaticParams` for `de`/`en`; root `app/page.tsx` is a static redirect page to `/de/` (meta refresh + link); `not-found.tsx` per locale; `public/404.html` produced by the export. |
| X5.2 | CSP: no inline scripts; styles via build-time CSS files; `report.html` is a separate document with its own CSP allowing its inlined styles (`style-src 'unsafe-inline'` only for that path). |
| X5.3 | `DashboardSlices` and `labels.json` become typed models in `core.models.dashboard` with JSON Schemas exported. |
| X5.4 | One rule: every `SliceDecision` appears in exactly one table — gated, informational (with `informational_reason`) or notable — defined in ui-spec and interfaces. |
| X5.5 | No-baseline state: `GateReport.baseline_run_id: RunId | None`, title emoji ⚪, `RunIndexEntry.no_baseline: bool`. |
| X5.6 | Tier-1 language/citation/refusal checks are **reported only**; tier-1 decides on hard fails and `error_rate` only (plus injection reported, X3.11). All docs say this. |
