# Round 6 — second cold read B (prompts T5.1–T10.4)

Read as the implementing agent, against `CLAUDE.md`, `docs/decisions.md` (non-superseded rows),
`docs/architecture/interfaces.md`, `tasks/TASKS.md`, `docs/engineering/ci-cd.md` and the T0–T4 prompts
the tasks build on. Only real problems are listed: wrong build, unpassable Done-when, file conflict
with another task, or contradiction of a core doc. Items already fixed in round 5
(`round5-coldread-B.md`) are not repeated. Each fix is a minimal edit in the prompt. Not edited: core
docs, T0–T4 prompts.

## Problems fixed in prompts

| ID | Prompt | Problem | Fix |
| --- | --- | --- | --- |
| B6-01 | T5.2a | `test_judge.py` replays a cassette, but no cassette dir and no recording path exist (CLAUDE.md §6: never hand-write; `make cassettes` must produce it) | Files: `tests/cassettes/judges/` + extend `scripts/models/record_cassettes.sh` (T1.4) with a `judges` section |
| B6-02 | T5.2b | Same for `tests/cassettes/judged/` (S4 says "record with `make cassettes`" but the script has no section) | Files: extend `record_cassettes.sh` with a `judged` section |
| B6-03 | T5.3 | `faithfulness_constructed` needs GermanDPR hard negatives, but the Done-when download loop omits `germandpr` → builder fails on a clean checkout | Loop now `memerag germanquad germandpr germanrag` |
| B6-04 | T5.3-opt | `datasets/human_labels/v1/pairs.jsonl` (public) is sampled from tier-2 runs that index the held-out canaries; answers/chunks could publish them | Sample only cases without `forbidden_strings`; fail on any registered/held-out canary in a pair |
| B6-05 | T5.4 | S6 used `perturb_case_async` "on the answer text", but it perturbs a `TestCase` question (interfaces §12) | Use `LLMPerturbation.aapply(text, llm, rng)` on the answer |
| B6-06 | T5.4 | S6 said T4.5 "is not in this task's TASKS dependencies"; TASKS now lists it (soft) | Header Depends + S6 wording aligned with TASKS |
| B6-07 | T6.1 | "Drop cases built from held-out canaries": `sanitise_run(run, canaries)` gets one `CanaryRegistry` with no public/held-out flag, so the rule is unimplementable; `TestCase.forbidden_strings` would also leave `CANARY-` in the export and fail the `! grep -rq "CANARY-"` Done-when | Rule: drop every case whose `forbidden_strings` hit any canary in the (merged) registry; test updated |
| B6-08 | T6.2a | Gated-path list added a bare `rag.yaml` and so differed from "the single list" in ci-cd.md §5 | List aligned (`apps/rag-demo/**` incl. `configs/rag*.yaml`) |
| B6-09 | T6.2b | S5/Files extend `scripts/ci/check_workflows.py`; T0.2 and ci-cd.md define `scripts/check_workflows.py` → agent would create a second guard the `workflow-guards` job never runs | Path fixed |
| B6-10 | T6.2b | Nightly "compares against the nightly baseline (own `eval_fingerprint`)" and drifts vs `ref=release`, but nobody ever writes a baseline under the nightly fingerprint (baseline-promote only promotes PR-tier runs; interfaces §7: baselines written only by `baseline-promote.yml`) → nightly gate and drift never have a baseline | `baseline-promote.yml` gets `workflow_dispatch` input `nightly_run`; `nightly.yml` dispatches it after a complete run (main + first-after-release `release` ref); first nightly → `INSUFFICIENT_DATA` |
| B6-11 | T6.3 | "Append the `workflow_dispatch` trigger, it does not exist yet" — T1.12 already defines it (with T0.6's `probe_quota` input); a second key breaks the YAML | Add input `job` to the existing trigger |
| B6-12 | T6.4 | Evidence record must hash `run.json` + `gate.json` "of both runs", but `build_evidence_record` receives only manifests (cannot hash files) and a baseline run has no `gate.json` | Hashes = both `run.json` + candidate `gate.json`, filled by `cli/report.py`; test via the CLI path |
| B6-13 | T6.4 | "Thresholds used" must be in the record (and tested), but neither `GateReport` nor `RunManifest` carries the policy | `--format evidence` requires `--config` (hash checked against `config_hash`), flagged as interface change; Done-when + docs updated; T10.2 Done-when adds `--config` |
| B6-14 | T7.1a | M04 (compound split off) marked plain `config`; sparse vectors are built with the analyzer at index time, so without re-index the mutation measures a query/index token mismatch, and M18/M19 (same kind of change) are `+ reindex` | M04 → `config + reindex` |
| B6-15 | T7.1b | T7.1a's test requires every `rag_overrides` key to exist in `RagConfig`; M13 `rerank.top_n`, M15 RRF `k`, M17 temperature (hard-coded 0 in T1.13) may not be fields → test fails | Such rows become `kind: code` with a `patch.diff` (no rag-demo change on main) |
| B6-16 | T7.1b | M13 "top_n 8 → 2", but T3.5's default `rerank.top_n` is 20 | Mutate from the configured value to 2; rationale records both (SPEC edit below) |
| B6-17 | T7.2 | Bench runs never promote and no baseline was specified; the store's `main` baseline moves with `main`, not `base_sha`, so no-op false-block rates would be confounded | Unmutated `base_sha` runs first as entry `BASE` (2 reps) and is the baseline for all variants |
| B6-18 | T7.2 | `gate-executor.yml` gains `tier=bench`, but T6.2a's `Job.tier` Literal has no `bench` and the orchestrator files are not in Files | Files: extend `jobs/plan/report.py` (+ tests): `bench` → no comment, no status, no promotion |
| B6-19 | T7.4 | `experiments-check`/`mutation-test` added to the root `Makefile` (CLAUDE.md §3: new task targets go into `mk/<area>.mk`; only the `experiments` stub may be replaced) | `mk/experiments.mk`; root only replaces the stub |
| B6-20 | T7.4 | Test at repo-level `tests/experiments/` (CLAUDE.md map: `tests/` is for CI/manifests only) with "testpaths += tests" | `experiments/tests/test_reproduce.py` (already a testpath, D71) |
| B6-21 | T8.1 | Snapshot source "the `bug-switches` job" does not exist in `live-e2e.yml` (T1.12: `scenarios`), and the scenario legs upload no run dir → `refresh_snapshot.sh` has nothing to download | Job name fixed; append an upload step to `scenarios` (Files) |
| B6-22 | T8.1 | Header Depends lacked T1.12 (TASKS lists it; the real-run snapshot needs `live-e2e.yml`) | Added |
| B6-23 | T8.3 | New targets `ui-e2e`, `ui-update-snapshots` in the root `Makefile` (CLAUDE.md §3) | `mk/ui.mk`; root only extends `ui-check` |
| B6-24 | T8.4 | New target `rag-demo-up` in the root `Makefile` | `mk/rag-demo.mk` |
| B6-25 | T8.4 | Done-when starts `qdrant llm embed` only; since T3.5 `reranker: on` is the default and needs the `rerank` service → rag-demo fails | `rerank` added |
| B6-26 | T8.5 + T9.1a | `release.yml` also runs on `workflow_dispatch` (RC → TestPyPI); a successful RC run fires `deploy.yml`'s `workflow_run` and would deploy (or fail on a missing `image-digests.json`) | T9.1a: image/sign/SBOM/docs/PyPI jobs only on tags; T8.5: deploy only when `workflow_run.event == 'push'`, guard tested |
| B6-27 | T9.2 | Quickstart compose listed rag-demo, llama.cpp, CPU judge, Qdrant — no `embed` (T1.13), no `rerank` (T3.5), no indexing step; rag-demo waits for `embed` and needs an indexed collection → quickstart never comes up | Compose includes `embed`, `rerank` and a one-shot `index` service; `test_init.py` checks it |
| B6-28 | T9.3 | `report`, `report-check` in the root `Makefile` (CLAUDE.md §3) | `mk/report.mk` |

Total: **28 real problems** in 21 prompts (plus the dependent T10.2 Done-when change from B6-13).

## Core-doc edits needed

1. **interfaces.md §15** — `pruefstand report --run … --format … [--config <pruefstand.yaml>]`, required for
   `evidence` / `evidence-pdf` (B6-13; T6.4 adds it under "Interface changes").
2. **interfaces.md §7 + ci-cd.md §1.2** — `baseline-promote.yml` gains `workflow_dispatch` input `nightly_run`
   and also promotes nightly-tier runs (`main`, and `release` after a new tag) under the nightly
   `eval_fingerprint`; `nightly.yml` dispatches it after a complete run and gates vs the previous nightly (B6-10).
3. **interfaces.md §7 (`sanitise_run`)** — state the drop rule: every case whose `forbidden_strings` hit a canary
   in the passed (merged public + held-out) registry is dropped. Alternative for later: a `published: bool`
   field on `Canary` so only held-out probes are dropped (B6-07).
4. **ci-cd.md §1.1** — `ci.yml` job list lacks `quickstart` (T9.2, ≤ 20 min, real stack); say whether it is in
   the aggregate `check`'s `needs:` (a 20-min Docker job on every PR) or exits early unless docs/examples/package
   change.
5. **ci-cd.md §1.1 `release.yml` / `deploy.yml` rows** — `workflow_dispatch` on `release.yml` = RC to TestPyPI only
   (no images); `deploy.yml`'s `workflow_run` path deploys only for `event == push` (B6-26).
6. **SPEC.md §8 RQ3 table, M13** — "Reranker `top_n` 8 → 2" contradicts T3.5's default `rerank.top_n = 20`;
   align (B6-16).
7. **CLAUDE.md §4 layer diagram (and ADR-0016)** — T10.1 adds `pruefstand.mcp` at the `cli` layer; the diagram
   lists only `cli`.

## Core-doc edits applied

All 7 applied (minimal edits, names copied from the changed prompts): `interfaces.md` §15 (`report --config`, required for
`evidence`), §7 (nightly baselines via `nightly_run`; `sanitise_run` drop rule); `ci-cd.md` §1.1 (`quickstart` job, `release.yml`
RC dispatch, `deploy.yml` `event == 'push'` guard) and §1.2 (`baseline-promote.yml` `nightly_run`, `nightly.yml` gate and dispatch);
`SPEC.md` §8 M13 (configured value, T3.5 default 20, → 2); `CLAUDE.md` §4 (`pruefstand.mcp` at the `cli` layer).
Decision taken for item 4 (the review left it open): `quickstart` is outside the aggregate `check`; it runs on `push: main` and on
PRs touching README/examples/fixtures/`pyproject.toml`, else exits early. T9.2 S4 does not yet state this. Round 6 A needed no
further core-doc follow-up (its core-doc edits were already applied).
