# Round 13 — cold read 8, senior developer lens

Reviewer stance: I have to implement every task from its prompt alone. Inputs read: `CLAUDE.md`,
`docs/decisions.md` (active rows; D248–D286 in full), `docs/architecture/{interfaces,components}.md`,
`tasks/{TASKS,PARALLEL-PLAN}.md`, `prompts/_lead-agent.md`,
`docs/engineering/{coding-standards,testing-strategy,test-matrix}.md`, `.env.example`, `docs/ops/secrets.md`, and
the `prompts/T*.md` files. I read Files, Interfaces, Tests and Done-when in all of them, plus the full text of T0.1,
T1.1, T1.3, T1.8, T1.9, T1.10, T4.1, T5.1, T6.1, T6.2a, T6.2b, T6.3 and T6.4. I also read
`round12-{dev,resolution,integration}.md`.

Checks run:

- every `open` test-matrix row compared with the owning prompt's "Tests to write first";
- the R12 contracts (N1 blocks and judged subset, N6.1 signatures, N6.2 test move, N6.3 per-root mypy, N6.4
  `/health` + `add_counts`, N6.5 derive path) traced through interfaces → prompts → matrix;
- env-var names in the prompts compared with `.env.example` and `secrets.md` (script);
- paths consumed but never produced (script, then a manual check of the hits);
- top-level module clashes across import roots (script);
- wave ownership overlaps.

**Verified fixed, not re-reported:** DEV12-01 (blocks, judged subset, CLI, `run_eval`, `nightly-b<k>` refs, drift
restriction: all present in T1.1/T1.8/T1.10/T4.1/T6.1/T6.2b and interfaces §2/§8/§14/§15/§17); DEV12-02 (T1.9
`set_check(..., infra_error)`, T6.4/T10.1/T10.2 `base … | None`, T6.2a uses the §10 text plus a `test_report.py`
case); DEV12-03 (`test_client_auth.py` in T1.13 Files, moved by T3.4/T3.6, which run in waves 9 and 11, so there is
no same-wave clash); DEV12-04 (per-root mypy loop, checker exemptions and their tests in T0.1); DEV12-05 (proxy
`/health` + `ArtifactStore.add_counts`); DEV12-06 (`scripts/dashboard/derive.py` + test inside `scripts/*/tests`);
DEV12-08 through DEV12-14.

Severity: **blocker** = an agent builds the wrong thing or cannot finish; **major** = likely rework or a
rule-5/rule-6 stop mid-wave; **minor** = a local fix.

## Test matrix: the 29 `open` rows

Totals are arithmetically right (241 covered + 29 open + 1 weak = 271 rows counted). But the legend
(test-matrix.md, "Status") defines **covered** as "the owning prompt has a concrete case", and **open** as "the
owning prompt's table did not yet contain" it. Against that definition, every one of the 29 open rows is already
covered by its prompt:

| Row (line) | Owner(s) | Prompt that already has the case |
| --- | --- | --- |
| `TestCase.block/judged_subset` (50), `RunManifest` R12 (55), `eval_fingerprint` R12 (60) | T1.1 | T1.1 `test_testcase.py`, `test_run.py`, `test_fingerprint.py` (all listed cases present) |
| `DatasetManifest` R12 (79) | T1.10 / T4.1 | T1.10 `test_dataset_models.py`; T4.1 repeats the same cases ("extend") |
| `LabelsDocument` (97) | T1.9 / T8.1 | T1.9 `test_labels.py` (`hard_fail_rules` dict) |
| Ollama translation (105) | T5.1 | T5.1 `test_qwen_thinking.py` (no `/v1`, catalogue miss at request time, non-Qwen, `PRUEFSTAND_GPU_CATALOGUE`) |
| `HttpTargetAdapter.retrieve` (126) | T1.3 | T1.3 `test_http.py` (`answer` key → `TargetError`) |
| `is_drift` (171) | T5.4 | T5.4 `test_drift.py` (R12 rule examples) |
| `add_counts` (182) | T1.8 | T1.8 `test_artifacts.py` |
| `LocalDirBaselineStore` refs (183) | T6.1 | T6.1 `test_baselines_local.py` |
| Heartbeat R12 fields (190) | T6.1 / T6.2a | T6.2a `test_health.py` (`false_since`); T6.1 only "incl. the health fields" |
| Runner `/v1/retrieve` routing (200) | T1.8 / T5.2b / T6.2a | T1.8 `test_runner.py`; T5.2b `test_runner_judges.py`; T6.2a `test_health.py`/`test_report.py` |
| `set_check(infra_error)` (227) | T1.9 | T1.9 `test_github.py` |
| Renderers `base=None` (228) | T1.9 / T6.4 | T1.9 `test_markdown.py`; T6.4 `test_html.py` (CSP for both), `test_evidence.py` |
| `assign_splits` (295), `validate_dataset` (296) | T4.1 | T4.1 `test_splits.py`, `test_validate.py` |
| `run_eval`/CLI blocks (304) | T1.10 | T1.10 `test_case_selection.py`, `test_commands.py` |
| Release drift + refs (306) | T6.1 | T6.1 `test_gate_refs.py` (the matrix names other files, DEV13-11) |
| `rerank.on_retrieve` + sampling (333) | T3.5 / T3.6 | T3.5 `test_api_retrieve.py`; T3.6 `test_generator.py` |
| `check_test_locations` (346) | T0.1 | T0.1 `test_check_test_locations.py` |
| T0.7/T3.1a/T6.2a/T6.2b/T8.1 rows (355, 363–365, 374, 375, 378, 389, 390) | as listed | their prompts' test tables (spot-checked 355, 374, 375, 378, 390) |

The matrix's own intro says these rows "stay `open` until those prompts' tests merge". That is a second meaning of
`open`, and it contradicts the legend. See DEV13-01.

## Blockers

None.

## Majors

| ID | Sev | Location | Finding | Fix |
| --- | --- | --- | --- | --- |
| DEV13-01 | major | test-matrix.md legend ("covered: the owning prompt has a concrete case") vs round-12 intro paragraph ("stay `open` until those prompts' tests merge"); multi-owner rows 79, 97, 190, 200, 228, 333 (one status for 2–3 tasks in different waves); `_lead-agent.md` step 13 ("test-matrix rows `covered`" before merge); T1.9 Done-when (flip "Renderers with `base=None` (T1.9 part)" → `covered`) | **Two meanings of `open`, and rows with one status for several owners, recreate the DEV12-07 merge stall.** Under the legend, all 29 open rows are already covered (table above), so the matrix misstates coverage. Under the "until merged" meaning, row 200 cannot become `covered` until T6.2a merges (wave 14). The lead's step 13 then blocks T1.8 (wave 5) and T5.2b (wave 10). Row 228 does the same to T1.9 (wave 6, T6.4 in wave 11), and row 97 to T1.9 (T8.1 in wave 12). T1.9 is told to flip a "part" of a row that has only one status cell. | Pick one meaning. Either (a) apply the legend: flip all 29 to `covered` and delete the "until merged" sentence, or (b) keep "until merged", but split every multi-owner row into one row per owner and change step 13 to "this task's rows". Fix stale row numbers in the prompts at the same time (DEV13-10). |
| DEV13-02 | major | interfaces §10 `set_check(sha, status: GateStatus, summary, *, no_baseline, infra_error)` and "the single mapping table … the only definition"; T6.2a:96/100/228 (`error` "executor unhealthy: NAS not mounted" / "…: gpu memory"), `test_health.py` (expects that text), S2/S8 (`pending` "awaiting run-gate label", success "not gated (release version bump)"); T6.2b (`pruefstand/nightly` success/failure, "skipped: maintenance") | **The executor must post statuses that the only status API cannot produce.** `GateStatus` has no `pending` and no `error`. The only way to get `error` is `infra_error=True`, which always prefixes "executor infra error:", so "executor unhealthy: gpu memory" (asserted in T6.2a's own test) is impossible. A `PASS` "not gated (release version bump)" would come out as "PASS: not gated …". No interface exists for `pending`, for a raw description, or for another context (`pruefstand/nightly`). The T6.2a agent has to invent a second poster (against "the only definition") or stop for an interface change in wave 14. | Pre-approve a second method, e.g. `GitHubPublisher.set_status(sha, state: Literal["pending","success","failure","error"], description: str, *, context: str = "pruefstand/gate")`, as the only path for non-gate states. Add the mapping rows to interfaces §10: preflight `error` "executor unhealthy: <reason>", `pending` "awaiting run-gate label", `success` "not gated (release version bump)", nightly context. Owner T1.9 (method + test), with matrix row and T6.2a/T6.2b call sites. Alternatively, change T6.2a's preflight to `infra_error=True` and its test text to "executor infra error: …". |
| DEV13-03 | major | interfaces §14 `assign_splits` comment (1186–1189: blocks "stratified by tenant x category"; judged subset "answerable, unanswerable and **injection** shares as in core"); SPEC §7.2 MDE table (≈ 110 answerable in the subset = 150 × 220/300, i.e. injection included); T4.1 Context 55–61 (blocks stratified by "category × tenant × **lang**"; subset "drawn from the answerable + `unanswerable` cases only (the 30 `injection` cases … never in the subset)"), T4.1 `test_splits.py` ("none `injection`"; "≤ 1 cluster per category × tenant × lang stratum") | **T4.1's prompt and tests contradict interfaces §14 and SPEC on what the judged subset and the block strata contain.** Without injection, the subset holds ≈ 122 answerable cases, not ≈ 110, so the SPEC MDE rows are off. The extra `lang` stratum changes the block allocation. CLAUDE.md §1.5 makes interfaces win, but the agent's own failing-first tests encode the other rule. Either the agent stops (rule 6), or the merged code and the MDE table disagree. | Decide one composition, write it into interfaces §14, SPEC §7.2 and T4.1 (Context + tests), with a decision row. The deterministic-only argument for excluding injection is sound; if adopted, update the SPEC MDE numbers. Also drop the duplicated `DatasetManifest` cases from T4.1 (T1.10 already has them) or mark T4.1's extension as "verify only". |
| DEV13-04 | major | T6.3 S4/test table (141, 185: the `refusal_policy` scenario runs "a fresh baseline run + switch run on the refusal stratum"); T6.2b `cause-switches` phase (same); SPEC §6.2 815; interfaces §15 `run_eval(..., block, judged_subset)` and CLI `--split/--block/--judged-subset` (no other case selector) | **No interface can run the refusal stratum alone.** `--block k` always adds block *k* (≈ 450 cases) to the refusal stratum; `--split full` without a block runs all of `full`. To get a refusal-only run, T6.3 must either run block+refusal twice on a Sunday night (≈ 1 200 cases, which breaks the T6.2b phase budget) or add a selector to T1.10's `run_eval`/CLI, an interface change in wave 16 (rule 6 stop). | Pre-approve the selector now: e.g. `--block refusal` (`run_eval(block=-1)` or `stratum: Literal["refusal"]`), recorded in `RunManifest.block` and the fingerprint. Owner T1.10, with a test row; T6.3/T6.2b call it. Or state in T6.3 that the refusal row runs on refusal + tonight's block and give its minutes in gpu-cluster.md §5. |

## Minors

| ID | Sev | Location | Finding | Fix |
| --- | --- | --- | --- | --- |
| DEV13-05 | minor | T1.10:48–49 (`auto` = Berlin `tm_yday` mod 3, computed at start); T6.2b `night-guard` (late starts accepted); SPEC §6.2 ("`full` covered every 3 nights") | `tm_yday mod 3` is not round-robin across Dec 31 → Jan 1 (365 → 2, 1 → 1; leap years 366 → 0, 1 → 1). A nightly delayed past 00:00 Berlin also takes the next day's block, so the following night repeats it. Either way a block is run twice in a row and another one is skipped. | Use `(date − 1970-01-01).days mod 3` on the scheduled night's date (the date of the 22:07 slot, not the start instant). Adjust the T1.10 clock tests. |
| DEV13-06 | minor | T6.2b `nightly.yml` row ("Release full run: … the gate phase runs `--split full` without `--block`"); interfaces §15 (`--ref nightly-b<k>` requires `block == k`); `test_nightly.py` (only the run argv is asserted) | The gate step of the release full run has no ref. `nightly-b<k>` is impossible (block `None`), and nothing says whether it gates against the previous `release` or skips gating. | State it: e.g. `gate --from-store --ref release` against the previous release run (same block-`None` fingerprint), or "no gate, promotion only". Add it to `test_nightly.py`. |
| DEV13-07 | minor | `docs/architecture/components.md` §3 `Generator` row ("the proxy enforces the catalogue `options`, Y3.2") and the rag-demo diagram (`/v1/query, /v1/info, /v1/health` only) | Stale against D252/N2 (the proxy enforces only `num_ctx`, `keep_alive`, allow-list; sampling passes through within `option_bounds`) and D218 (`/v1/retrieve`). | Reword the row per D252; add `/v1/retrieve` to the diagram node. |
| DEV13-08 | minor | CLAUDE.md §3 "Local stack" + D278 ("never raw `docker compose`") vs PARALLEL-PLAN §1 rule 7 / docker.md (`make ports-env` makes raw compose safe) and the raw `docker compose --profile live up …` Done-when lines in T1.4, T1.11, T1.13, T3.4, T3.5, T4.7a, T5.1, T5.2b, T6.1, T10.3, T6.2a, PARALLEL-PLAN waves 2/5 checkpoints | Agents copy the Done-when commands verbatim and break the binding D278 rule; the plan and docker.md say it is fine after `make ports-env`. | Either amend D278/CLAUDE.md to "raw compose only after `make ports-env` (checked by `make check-ports`)", or rewrite those Done-when lines as `make up PROFILES="core live dev"`. |
| DEV13-09 | minor | `secrets.md` / `.env.example` vs T3.1a:109/172 (`PRUEFSTAND_TRUSTED_CHECKOUT`), T0.4/T8.5 (`PAGES_MAX_BYTES`), T0.1/T0.2 (`HYPOTHESIS_PROFILE`, `LITELLM_LOCAL_MODEL_COST_MAP`) | CLAUDE.md §5 says **every** environment variable has a `secrets.md` row. These four have none (script check; GitHub-provided `GITHUB_*` excluded). | Add four rows (CI/Make-only scope for the last three) and a commented `.env.example` line for `PRUEFSTAND_TRUSTED_CHECKOUT`. |
| DEV13-10 | minor | T5.2b:158 ("row 185"), T6.4:22/131/132/152 ("row 213"), T8.1:165/209/241 ("row 371") | Stale row numbers. After the R12 refresh these rows are at lines 200, 228 and 390. | Refer to rows by symbol name only. |
| DEV13-11 | minor | test-matrix row 306 (test files `test_gate_from_store.py`, `test_baseline_cli.py`) vs T6.1 Files/tests (`pt/unit/pipeline/test_gate_refs.py` holds every N1.4 case) | The matrix points to the wrong file. | Name `test_gate_refs.py` in row 306. |
| DEV13-12 | minor | T1.9 Files (no `schemas/labels.schema.json`, no `core/schema.py` registration hunk) vs T1.9 Context 113–115 ("registers it for `make schemas`") and `test_labels.py` ("validates against `schemas/labels.schema.json`"); T8.1 Files lists the same schema as "generated"; wave-6 checkpoint `make schemas-fresh` | T1.9's test reads a file that its Files list does not produce. If T1.9 registers the model without committing the schema, `schemas-fresh` fails at the wave-6 checkpoint. If it skips registration, its own test has no schema. | Add `core/schema.py` (register, own hunk) and `schemas/labels.schema.json` to T1.9 Files; T8.1 only regenerates it. |
| DEV13-13 | minor | PARALLEL-PLAN wave 3 (T1.2 owns `core/config/**`) vs T1.2/T2.5/T4.1/T10.3 Files (`core/config.py`, one module holding ≈ 15 models: interfaces "Where types live" `core.config` + build configs); CLAUDE.md §5 300-line limit | The file shape differs between plan and prompts. With docstrings and validators, the single module is likely to exceed 300 lines by T4.1 or T10.3 (`make file-size` red). That forces a split into a package that later prompts' Files lists do not name. | Make T1.2 create the package `core/config/` (`__init__.py` re-exporting; `run.py`, `build.py`, …) and point T2.5/T4.1/T10.3 at `core/config/build.py` / `target.py`. |

## Counts

| Severity | Count |
| --- | --- |
| blocker | 0 |
| major | 4 |
| minor | 9 |
| **total** | **13** |

The round-12 fixes reached the prompts. This time the Interfaces blocks, test tables and Files lists carry the N1
and N6 changes. The remaining risk is in three places. First, matrix bookkeeping (DEV13-01). Second, two
operational paths that no interface covers yet: non-gate commit statuses (DEV13-02) and a refusal-only run
(DEV13-04). Third, T4.1, whose judged-subset rule drifted from interfaces/SPEC (DEV13-03). Each of these would
otherwise stop a task mid-wave in waves 5–16.
