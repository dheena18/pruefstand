# Round 13 resolution — binding decisions (cold read 8: 0 blockers, 15 majors)

Inputs: `round13-dev.md` (0/4/9), `round13-ai.md` (0/3/12), `round13-ui.md` (0/5/15), `round13-arch.md` (0/3/11).
Overrides earlier resolutions where they conflict. Apply every minor with the reviewer's exact fix unless it conflicts with this file.

## P1 Security: gate trigger and required status (A13-01)

| # | Decision |
| --- | --- |
| P1.1 | `gate-router.yml` posts `pruefstand/gate` with the **`pruefstand-bot` App token** (secret in environment `gate-router`, usable only by that workflow on `pull_request_target`, still no checkout). The ruleset **pins** `pruefstand/gate` to the `pruefstand-bot` App again. A branch workflow using `GITHUB_TOKEN` can no longer satisfy the check. |
| P1.2 | The tier-2 gate trigger for PRs is **only** a `workflow_dispatch` of `gate-executor.yml` in the private repo (input `pr`), started by the owner from the browser or the GitHub mobile app. The VM token has no access to the private repo, so agents cannot trigger it. The `run-gate` label is removed. `main` pushes and nightlies stay automatic. Fork PRs: owner pushes `gate/pr-N`, then dispatches. |
| P1.3 | security.md C18 and the runbook state exactly what the VM token can do (push branches, open PRs, push workflow files) and that none of it can produce `pruefstand/gate` or start tier 2. |

## P2 Nightly guard and demo isolation (A13-02, A13-03)

| # | Decision |
| --- | --- |
| P2.1 | The guard job sets output `run=true|false`; the nightly job has `if: needs.guard.outputs.run == 'true'`. A nightly whose start is after 06:00 Berlin ends at once with `infra_error="window_exceeded"`, reported once per night (no duplicate issue). |
| P2.2 | `demo-net` egress: DOCKER-USER drops traffic from `demo-net` to `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and the VM's own addresses; only `cloudflared` reaches the internet. |

## P3 Data composition and research validity (AI majors)

| # | Decision |
| --- | --- |
| P3.1 | `full` composition quota: refusal stratum ≈ 150 cases (every night) + 3 blocks × 450 cases. Each block = 300 unperturbed answerable cases (≥ 250 clusters, per-tenant ≥ 30) + 150 perturbed variants. Written in SPEC §3/§6.2 and enforced by `validate_dataset` (T4.1). |
| P3.2 | RQ1 uses its own split **`rq1`** (300 bases × applicable perturbations), run offline in `experiments/`, never in the nightly. `Split` gains `RQ1`. RQ1 limits generation to its subsample and compares chunking at equal text volume (equal total tokens retrieved), not equal k. |
| P3.3 | RQ3: every mutation's **true effect** is measured on a large reference run (all 3 blocks + refusal stratum, 3 seeds, paired with a matched BASE re-run per mutation). Detection rate is computed only over mutations whose true effect ≥ δ ("should-detect"); the others are reported separately. M14 is replaced by "embedding input truncated to 128 tokens". Only FAIL counts as detection (WARN reported separately). |
| P3.4 | PR budget fallback works on the bottleneck: `judged_subset` (the fixed 150-case subset) applies to **generation and judging** of `core` answerable cases in PR runs when T3.1b measures the budget is exceeded; deterministic security cases always run in full. The subset is stratified by category **including injection**, no `lang` stratum (interfaces §14 wins; T4.1 aligned). |

## P4 Contracts (dev majors)

| # | Decision |
| --- | --- |
| P4.1 | test-matrix statuses: `covered` (owning prompt contains the concrete test), `planned` (test specified, owner task not yet merged — informational only, never blocks merge), `weak`. Rows with several owners are split into one row per owner. |
| P4.2 | New low-level `GitHubPublisher.post_status(sha, state, description, context="pruefstand/gate")`; `set_check` is a wrapper for gate results. The executor uses `post_status` for "pending", "executor unhealthy"; "not gated" is posted only by gate-router. Owner T1.9 (function), T6.2a (use). |
| P4.3 | CLI `pruefstand run --split full --stratum all|refusal|blocks` (`run_eval(..., stratum=...)`); the nightly uses `--stratum all --block auto`; T6.3/T6.2b use `--stratum refusal` where needed. Owner T1.10. |
| P4.4 | Block rotation uses a persisted counter `state/nightly_counter` (`k = counter mod 3`, incremented only after a completed nightly), not the date. |

## P5 UI / deploy (UI majors)

| # | Decision |
| --- | --- |
| P5.1 | `push_dashboard_data` rewrites the **whole** published tree from the index each time (last 200 runs; shards + report.html for the newest 20), so old data is pruned. Owner T6.1. |
| P5.2 | The workflow guard allows `actions: read` for the `fetch-artefacts` job of `release.yml` only (allowlist entry with reason). |
| P5.3 | Demo lookup: one anonymous API call (`releases/latest`) per night; assets downloaded via `browser_download_url` (not the API). |
| P5.4 | Test reset: called from inside the container (`docker compose exec rag-demo-e2e curl -X POST localhost:8000/v1/_test/reset`), so loopback is real. |
| P5.5 | Every Pages build writes `build-id.txt` (commit SHA); post-deploy smoke polls `/pruefstand/build-id.txt` until it matches (max 10 min), then runs the checks. |
