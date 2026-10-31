# Round 7 — third cold read B (prompts T5.1–T10.4)

Read as the implementing agent, against `CLAUDE.md`, `docs/decisions.md` (non-superseded rows),
`docs/architecture/interfaces.md`, `tasks/TASKS.md`, `docs/engineering/ci-cd.md` and the T0–T4 prompts the
tasks build on. Also checked across tasks: (a) prompts that can run at the same time (no dependency path
between them) must not edit the same file; (b) every file a prompt uses must come from one of its
(transitive) dependencies. Items from rounds 5 and 6 (`round5-coldread-B.md`, `round6-coldread-B.md`) are
not repeated. Each fix is a minimal edit to the prompt. Not edited: core docs, T0–T4 prompts.

## Problems fixed in prompts

| ID | Prompt | Problem | Fix |
| --- | --- | --- | --- |
| B7-01 | T5.1 | S4/S5 change the pipeline, and the Done-when runs `pruefstand run` with `examples/live/pruefstand.yaml`. Both come from T1.10, which is not a transitive dependency of T5.1 (T1.4, T1.8, T3.1b) | Depends + T1.10 |
| B7-02 | T5.1 | S2 extends `llm/policy.py`; S4/S5 have the pipeline pass `DiskKVCache` and the fallback backend and set `RunManifest.judge_fallback`. None of these files is in Files, so the agent stays inside `llm/` and `judge_fallback` is never set | Files: `llm/policy.py`, `pipeline/run.py`, `pipeline/judge_mode.py` |
| B7-03 | T5.1 | The `test_budget.py` (unit/llm) row asserts the pipeline's `complete=False` and the gate's `GateInputError`. That cannot run as an offline `llm` unit test without a target (no fakes). Both are already covered by T1.8 `test_budget_stop.py` and T1.7 | Row limited to the llm-level assertions, with pointers to the existing tests |
| B7-04 | T5.2a, T5.2b | `scripts/models/record_cassettes.sh` also gets sections from T4.2 and T4.5. All four need only T5.1, so they can run in parallel on one file that is not append-only | Shared-file note: append only your own section, in the last commit, and rebase |
| B7-05 | T5.1, T5.2b, T5.4, T6.1 | `pipeline/run.py` (T5.1, T5.2b, T6.1) and `examples/live/pruefstand.yaml` (T5.2b, T5.4, T6.1) are edited by tasks with no dependency between them (T6.1 needs only T1.10) | Shared-file note in each: not in parallel worktrees, small hunk in the last commit, rebase |
| B7-06 | T6.1 | `cli/baseline.py` must be registered in `cli/__init__.py`, and T1.10's `baseline promote` stub must be removed from `cli/stubs.py`. Neither file is in Files. T2.5 (same lane after T1.10) edits both files to replace the `ingest` stub | Files + shared-file note |
| B7-07 | T6.1 | `gate --from-store` with no stored baseline is undefined. T6.2a's `dry-run --tier main` ("writes `gate.json`") and T6.2b's first nightly (`INSUFFICIENT_DATA`, "not a failure") depend on it. A natural `StoreError` gives exit 3 | Rule: `gate.json` with `INSUFFICIENT_DATA`, `baseline_run_id` = candidate id, exit 0; new test `test_gate_from_store.py` |
| B7-08 | T6.1, T8.1 | `sanitise_run` needs a `CanaryRegistry`, but `baseline export-public` and `export-dashboard` take no registry and nothing says where it comes from. The `! grep CANARY-` Done-when (T6.1) and the leaked-canary export test (T8.1) cannot pass | `store/canary_source.py` `load_canary_registry()`: slice `corpus/*/canaries.public.json` + T2.6 registries + held-out via `PRUEFSTAND_HELDOUT_DIR`; none found → `StoreError`; T8.1 reuses it |
| B7-09 | T6.2a, T6.2b | The executor sync used `scripts/sync_executor.sh vX.Y.Z`, but `v*` tags may only be created by the release App (ci-cd.md §5, ADR-0017), they trigger `release.yml`/PyPI, and release-please only exists from T9.1a. T6.2b also had no sync step, yet its [GPU] Done-when lines need the workflows on the private `main` | Tags `executor-<YYYYMMDD>[.N]` on `main` (script refuses others); T6.2b S7 [HUMAN] tag + sync + merge in the private repo before the GPU checks |
| B7-10 | T7.2 | `run_all.py` dispatches `gate-executor.yml -f tier=bench`, which only works once S1b is merged to public `main` **and** synced to the private repo. As one PR it can never be run before merge | S1b lands first as its own PR → `executor-*` tag + sync; preregistration still comes first |
| B7-11 | T6.3 | The cause-switch candidates `reranker: off + top_k: 3` and "closed generator port" do not exist. If placed in `configs/bugs/` they break T1.13's `test_config.py` ("every bug config differs in exactly one field") | Reuse T1.13's three single-switch bug configs; the two others go in `apps/rag-demo/configs/cause/` (Files) |
| B7-12 | T6.3, T7.2 | `gh workflow run live-e2e.yml -f job=…` without `--ref` runs `main`'s copy, which has no `job` input / `dose-response` choice before merge, so the Done-when fails | `--ref <branch>` |
| B7-13 | T6.3, T6.4, T7.2, T8.1 | All four extend `.github/workflows/live-e2e.yml`. T6.4 and T8.1 have no ordering with T6.3/T7.2 or with each other | Shared-file note (append, last commit, rebase) |
| B7-14 | T6.3, T6.4, T7.2, T10.2 | They edit files created by T1.12 (`live-e2e.yml`; `action/Dockerfile` for T10.2), but T1.12 is not in their transitive dependencies | Depends + T1.12 |
| B7-15 | T6.4 | `--config` is rejected when "the file's hash ≠ `RunManifest.config_hash`". T1.10 fills `config_hash` without stating the method. A raw-bytes hash would never match, so `--format evidence` would always exit 2 and the Done-when fails. The `live-e2e.yml` render step also lacked `--config` | Reuse T1.10's config-hash function; S4 passes `--config examples/live/pruefstand.yaml` |
| B7-16 | T7.4 | "`experiments-check` … so it can be a required check" contradicts ci-cd.md §1 (only the aggregate job is required; `experiments-check` is in `check`'s `needs:`) | Added to the aggregate `check` `needs:`; no separate required check |
| B7-17 | T8.4 | `e2e/try.spec.ts` and the `try-it` job need T8.3's `playwright.config.ts`/Playwright setup. Both tasks edit `ui.yml` and `apps/dashboard/package.json`, but T8.4 depends only on T8.2b/T3.7 | Depends + T8.3 |
| B7-18 | T8.5 | `deploy.yml` consumes `release.yml` and its `image-digests.json` (T9.1a), and the "Release → deploy green" Done-when needs them, but T9.1a is not a dependency. Both extend `scripts/tests/test_check_workflows.py` with no ordering | Depends + T9.1a |
| B7-19 | T9.2 | The `quickstart` legs run in clean `python:3.12-slim` / `ubuntu:24.04` images "with only curl". There is no Docker there, and a job `container:` cannot reach compose ports on `localhost`, so the real stack never starts | Legs started with `docker run --network host` + mounted socket; Docker CLI/compose is the only prerequisite installed |
| B7-20 | T9.2 | The S4 trigger paths omit `packages/pruefstand/src/pruefstand/examples/**`, which ci-cd.md §1.1 lists. Changes to the quickstart package data would not run the job | Path added |
| B7-21 | T8.1, T9.2, T10.1, T10.4 | New commands (`export-dashboard`, `init`, `mcp`, `drift`) must be registered in `cli/__init__.py` (T1.10 convention), but none of them lists the file. T9.2, T10.1 and T10.4 have no ordering | Files entry + "one line, last commit, shared" note |
| B7-22 | T10.1 | `compare_runs(baseline_run_id, candidate_run_id)` must call `run_gate(candidate, baseline, cfg)`, which needs a `PruefstandConfig`. The tool had no way to obtain one | Tool takes `config_path` (workspace-root rule; test uses `examples/live/mini.yaml`) |
| B7-23 | T10.3 | The live test and the Done-when use `pruefstand run` (T1.10) and the `live` compose stack + slice corpus (T1.13). It depends only on T1.3 | Depends + T1.10, T1.13 |
| B7-24 | T10.4 | It scores the judged `faithfulness` registry metric (T5.2b) but depends only on T6.1 | Depends + T5.2b |

Total: **24 real problems** in 21 prompts.

## Core-doc edits needed

1. **TASKS.md Depends** (and Unblocks where shown): T5.1 + T1.10; T6.3, T6.4, T7.2, T10.2 + T1.12; T8.4 + T8.3;
   T8.5 + T9.1a; T10.3 + T1.10, T1.13; T10.4 + T5.2b (B7-01, B7-14, B7-17, B7-18, B7-23, B7-24).
2. **CLAUDE.md §3 + TASKS.md "Shared append-only files"**: add `scripts/models/record_cassettes.sh`,
   `.github/workflows/live-e2e.yml`, `packages/pruefstand/src/pruefstand/cli/__init__.py` (+ `cli/stubs.py`) and
   `examples/live/pruefstand.yaml`. TASKS "Parallel lanes": T6.1 must not run in parallel with T5.1/T5.2b/T5.4
   (`pipeline/run.py`, `examples/live/pruefstand.yaml`), and T6.1 ∥ T2.5 share `cli/__init__.py`/`cli/stubs.py`
   (B7-04, B7-05, B7-06, B7-13, B7-21).
3. **ci-cd.md intro (line 22) + ADR-0005**: executor sync at a maintainer tag `executor-<YYYYMMDD>`, not
   `vX.Y.Z` (v* tags belong to the release App and trigger `release.yml`) (B7-09).
4. **interfaces.md §15**: `pruefstand gate --from-store` with no baseline for (fingerprint, ref) → `gate.json`
   `INSUFFICIENT_DATA`, `baseline_run_id` = candidate id, exit 0 (B7-07). **§7**: `store/canary_source.py`
   `load_canary_registry() -> CanaryRegistry` is the registry source of `export-public` / `export-dashboard`
   (B7-08).
5. **interfaces.md §2/§15 (`RunManifest.config_hash`)**: say how `config_hash` is computed (e.g.
   `stable_hash(cfg)` over the parsed `PruefstandConfig`), so T6.4's `--config` check has one definition (B7-15).
6. **ci-cd.md §1.1 `ci.yml` row (`quickstart`)**: legs run via `docker run --network host` with the Docker socket
   mounted; Docker is the quickstart's stated prerequisite (B7-19).

## Applied (core-doc edits)

All 6 items applied. `tasks/TASKS.md`: Depends cells for T5.1, T6.3, T6.4, T7.2, T10.2, T8.4, T8.5, T10.3, T10.4 now equal their
prompts (T8.5 keeps `+T8.4 if done`); the shared-file note lists `record_cassettes.sh`, `live-e2e.yml`, `cli/__init__.py` +
`cli/stubs.py`, `examples/live/pruefstand.yaml`, `pipeline/run.py`; new lane row: T6.1 not in parallel with T5.1/T5.2b/T5.4.
`CLAUDE.md` §3 shared-file sentence extended (merged with the round-7 A edit). `ci-cd.md`: executor tag `executor-<YYYYMMDD>`, quickstart
legs via `docker run --network host`. ADR-0005: same tag rule. `interfaces.md`: `config_hash = stable_hash(parsed PruefstandConfig)`,
`gate --from-store` no-baseline rule, `store/canary_source.py load_canary_registry()`. A scripted check of all prompt "Depends on"
cells against TASKS.md rows now shows no differences.
