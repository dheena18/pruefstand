# Round 12 resolution — binding decisions (cold read 7)

Inputs: `round12-dev.md` (1/6/7), `round12-ai.md` (0/3/9), `round12-ui.md` (0/5/15), `round12-arch.md` (0/5/12).
Overrides earlier resolutions where they conflict. Apply every minor with the reviewer's exact fix unless it conflicts with this file.

## N1 Nightly rotation and judged subset as contracts (DEV12-01, AI major 1)

| # | Decision |
| --- | --- |
| N1.1 | `TestCase` gains `block: int \| None` (0, 1, 2 for answerable/other `full` cases; `None` for the refusal stratum, which runs every night) and `judged_subset: bool = False` (fixed seeded 150-case subset of `core`). Assigned by **T4.1** (`assign_splits`), recorded in `DatasetManifest`. |
| N1.2 | CLI: `pruefstand run --split full --block auto\|0\|1\|2` (`auto` = ISO day-of-year mod 3, computed in Europe/Berlin) and `--judged-subset` for PR runs. `run_eval(..., block: int \| None = None, judged_subset: bool = False)`. Owner **T1.10**. |
| N1.3 | `RunManifest.block: int \| None`, `RunManifest.judged_subset: bool`; both are part of `eval_fingerprint`. |
| N1.4 | Baselines: nightly compares with baseline ref **`nightly-b<k>`** (the latest promoted main nightly of the same block); PR runs with ref `main`; drift vs `release` uses the release run's cases restricted to the same block. Owner **T6.1** (refs) and **T6.2b** (scheduling). |

## N2 llm-proxy option policy (AI major 2)

The proxy enforces only `num_ctx` and `keep_alive` (and the model allow-list); `temperature`, `seed`, `top_p`, `num_predict` pass through from the client within catalogue min/max bounds. Catalogue values are defaults, not overrides. Mutation M17 and T6.3 churn runs work as designed.

## N3 Drift rule (AI major 3)

Drift = number of changed anchor verdicts ≥ `max(3, ceil(0.1 · n))` (n = anchors, 50 → 5), for both hosted and local judges. `is_drift(..., a0=)` keeps the signature; the rule above replaces the Wilson form.

## N4 Ops (arch majors)

| # | Decision |
| --- | --- |
| N4.1 | `pruefstand-tunnel.service` has **no** dependency on the NAS mount. The runner uses `Wants=` + `After=` on the mount (not `Requires=`); preflight fails the job with `infra_error="nas_unavailable"` if the mount is missing. |
| N4.2 | Firewall: rules go into Docker's **`DOCKER-USER`** chain via a systemd oneshot `pruefstand-firewall.service` (`After=docker.service`, re-applied on Docker restart); never flush or reload the full ruleset via `nftables.service`. |
| N4.3 | Nightly: before each phase the job checks remaining time to 06:00 Berlin; if not enough, it stops gracefully with `stop_reason="aborted"`, `infra_error="window_exceeded"`; a nightly that could not start is reported (heartbeat field `last_nightly_status` + issue "nightly skipped"), never silent. |
| N4.4 | The owner's `gh` on the VM uses a **fine-grained token** limited to the public repo (contents + pull requests write, no admin, no private repo). Admin actions (labels on the private repo, bypass) are done from the owner's Windows browser. Security row C18 updated. |
| N4.5 | `docs.yml`: concurrency group per ref for build jobs; the `pages` group only on the deploy job. |

## N5 UI (UI majors)

| # | Decision |
| --- | --- |
| N5.1 | Size cap: export keeps the last 200 runs in the index and case shards for the last 20 runs; a CI step fails if the assembled site > 800 MB. |
| N5.2 | `docs.yml` is triggered by **`workflow_run`** on successful `deploy.yml` (plus its own triggers), downloading the `dashboard-site` artefact from `github.event.workflow_run.id`; no dispatch, no run-id search. |
| N5.3 | Demo deploys the public GHCR image by digest (no artefact download, no token). |
| N5.4 | Try-it tests: a reset endpoint `POST /v1/_test/reset` exists only when `DEMO_TEST_RESET=1` and binds to loopback; each of the 8 combinations resets before running. |
| N5.5 | A required PR check builds the dashboard with `basePath=/pruefstand` and runs a Playwright smoke at `/pruefstand/`. |

## N6 Dev majors

| # | Decision |
| --- | --- |
| N6.1 | Prompts' own Interfaces blocks carry the R11 signatures: T1.9 `set_check(..., infra_error)`, T6.4/T10.1/T10.2 `base: RunResults \| None`, T6.2a uses the exact error-status text from interfaces §10 and passes `infra_error=True`. |
| N6.2 | `test_client_auth.py` is in T1.13's Files list; T3.4 and T3.6 move it with the modules they replace. |
| N6.3 | Tests per import root stay in `<root>/tests/`; pytest importlib mode allows duplicate basenames; `make typecheck` runs mypy **per root** (loop), so duplicate test module names never collide; `check_test_locations` allows `<root>/tests/` for every root in the CLAUDE.md list. |
| N6.4 | llm-proxy `/health` returns `{model_reloads, upstream_errors, requests}`; the orchestrator reads it before/after a run and the runner writes `counts["model_reloads"]` and `counts["upstream_errors"]`. Owner T6.2a; shape in interfaces §1.5. |
| N6.5 | The derive script moves to `scripts/dashboard/derive.py` with tests in `scripts/dashboard/tests/test_derive.py` (inside testpaths); ui-spec and T8.1/T8.3 updated. |
| N6.6 | test-matrix: apply DEV12-07 exactly (7 rows → covered with correct file names; rows 113/185 reassigned to T1.3/T1.8 with the missing cases added to those prompts; rows 92, 212, 213 (T6.4 part), 371 get their tests added to T5.1, T1.9, T6.4, T8.1). |

## N7 AI minors of note

Gemma nightly judge `num_ctx` 12288 (verify sliding-window behaviour in T3.1b); everything else per `round12-ai.md`.
