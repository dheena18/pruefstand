# Round 2 — verification of round-1 fixes + consistency sweep

Reviewer: independent round-2 reviewer. No project file edited. `SPEC-v1-original.md` and `.review/` ignored
(except as inputs). Line numbers refer to the files as they are now.

Summary

- **Task A** (every blocker + major of the three round-1 files, 126 items): **111 resolved · 15 partly · 0 open · 0 regressed**.
- **Task B** (new issues only): **2 blocker · 13 major · 25 minor** (40).

Checks that passed in Task B: no reference to a deleted task ID (T1.5, T3.1, T4.7, T5.2, T6.2, T7.1, T8.2, T9.1)
outside the intentional split notes (`docs/decisions.md:67`, `prompts/README.md:100-101`); every TASKS ID has
exactly one prompt file and a README index row; every prompt header "Depends on" equals the TASKS row
(ignoring parenthesised notes); every `docs/adr/*.md` path referenced exists; no `cli.py`, `cli_commands/`,
`llm/litellm_backend.py`, `llm.fake`, `pipeline/fingerprints.py`, `core/fingerprints.py`, `metrics/data/law_aliases.yaml`,
`gate-gpu.yml`, `gate-pr.yml`, `baseline-main.yml`, `gate-nightly.yml` anywhere; α 0.025, warn_p 0.10,
min_clusters 30, B 10 000, gated slices (`overall`, `tenant`, `lang`, + `perturbation` for retrieval metrics),
δ defaults (0.05 / 0.03 refusal) and the hard-fail list (`canary_leak`, `tenant_leak`, `system_prompt_leak`)
agree across CLAUDE.md, interfaces, SPEC, ADR-0007, decisions.md, T1.2, T1.6, T1.7, T6.3.

---

## Task A — verification table

### A.1 `round1-consistency.md` (4 blockers, 33 majors)

| id | status | evidence | remaining fix |
| --- | --- | --- | --- |
| B1 | resolved | T0.1:45,80 (`cli/__init__.py`, "Never create `cli.py`"); T1.10:39,56,68; interfaces:569-570; SPEC:394; T2.5:71, T4.1:87, T4.7a:69, T6.1:72, T10.1:48, T10.4:54 all `cli/<cmd>.py` | – |
| B2 | resolved | T6.3:83-84 (no `higher_is_better`), T6.3:104 | (but see Task B N1: `confidence` field) |
| B3 | resolved | CLAUDE.md:101; interfaces:372-374; ADR-0016:17 (`metrics` forbidden); components.md:43,52; T1.7:31-33,108 | – |
| B4 | resolved | T5.1:42-43,59 (`llm/backends/litellm.py`, contract exists since T0.1); interfaces:193,211 | – |
| M1 | resolved | ADR-0007:22-24,49; call-graph.md:80,99-100; interfaces:439-441; SPEC:623-625 | – |
| M2 | resolved | SPEC:436,573-576,643; call-graph.md:37; interfaces:412 | – |
| M3 | partly | SPEC:427-436,448-450,463 fixed (ModelRef judges, no direction, budget names, store type) | SPEC:438-444 still give `confidence: 0.95` per metric; interfaces:410 `MetricPolicy` has no such field (`extra="forbid"`) → see N1 |
| M4 | resolved | interfaces:545-546 (`fake_degradations_path`); T1.10:36; T1.2:45(e) | – |
| M5 | resolved | interfaces:38,263,493; T5.2b:72; T4.5:76-77; T1.4:49,90; T1.8:49 | – |
| M6 | resolved | components.md:15,29-34,50 (`metrics` own row) | – |
| M7 | resolved | components.md:67,69,73 (ingest/attacks used by pipeline only); call-graph.md:148 | – |
| M8 | partly | T0.1:52 creates all seven ADR-0016 contracts with exact names | components.md:48-55 lists 6 contracts (no `siblings-independent`) and words `llm-gateway` as "importable only from `pruefstand.llm.backends`" (ADR-0016:18: only `pruefstand.llm.backends.litellm`). Copy ADR-0016:14-22 verbatim into components.md §1 |
| M9 | resolved | ADR-0008:16-24 (9 kinds); decisions.md:18; testing-strategy.md:51 | – |
| M10 | resolved | ADR-0008:25 `pruefstand.llm.backends.fake`; no `llm.fake` left | – |
| M11 | resolved | ADR-0009:29-30 (`core/models_family.py`) | new duplicate table, see N5 |
| M12 | partly | interfaces:363, ADR-0006:19, SPEC:369, decisions.md:52 use the 8-part key | data-model.md:242 still `stable_hash(model, prompt_id, prompt_version, rendered messages, temperature, seed)` → add `max_tokens`, `response_format` |
| M13 | resolved | T6.2b:25-27,68-72,89-93; ci-cd.md:28,38-40; no old names anywhere | – |
| M14 | partly | ADR-0005:66-74 and ci-cd.md:28,157-158 define one trigger rule | T6.2b:42-52 differs (adds `opened, reopened`, `release: published`, drops cron; removes label on `synchronize` while ci-cd.md:157 re-requires env approval) → see N7 |
| M15 | resolved | T6.2a:6 (T4.7b in deps), T6.2a:75 S0 re-index | – |
| M16 | resolved | TASKS.md:75 = T4.2:6 (T4.1, T5.1, T2.3, T2.4) | – |
| M17 | resolved | TASKS.md:40 T1.8 → T1.3, T1.4, T1.5b; T1.7 +T1.2; T1.12 +T0.5 | – |
| M18 | partly | SPEC:689-706 single table with `code` column; T1.7:50; T6.3:51-54; interfaces:436 | T1.7:91,93 and T1.11:84 cite rule numbers that point at the wrong rows after `errors` became rule 3 → see N3 |
| M19 | resolved | T6.3:62,72 (extend `test_cause.py`), no `test_likely_cause.py` | – |
| M20 | resolved | interfaces:443-445; T1.7:49; SPEC:647 | – |
| M21 | resolved | T1.7:33-34 (`dimension="overall"`), T1.7:44 (per gated slice); SPEC:638-641 | – |
| M22 | resolved | interfaces:276-282; T1.5a:41,89-90 | – |
| M23 | resolved | T1.5a:31,56; T4.4:43,55; T1.5b:103; SPEC:287 | – |
| M24 | resolved | interfaces:589-590; T3.2:45; components.md:117; T3.3:78/T3.6:73 only use the types | – |
| M25 | resolved | interfaces:27,180,619; T1.1:50,76; T6.1:45,57; T2.5:6,20 | (signature drift, see N4) |
| M26 | partly | interfaces:329, data-model.md:283-286, T6.1:33-34, decisions.md:50, sequences.md:95 use `baselines/<eval_fingerprint>/<ref>/` (R2.7) | ADR-0004:18-19 and ci-cd.md:68 still say `baselines/<ref>/<eval_fingerprint>/`; file names differ (`responses.jsonl.zst` + `manifest.sig` in ADR-0004/T6.1 vs `responses.jsonl.gz` + `manifest.sigstore.json` in data-model.md:285-286). Align ADR-0004 and ci-cd.md to R2.7 and pick one file set |
| M27 | resolved | T0.2:79 (`dataset-release.yml`: T9.1b); T9.1b:43 `environment: huggingface`; ci-cd.md:32 | – |
| M28 | resolved | T8.1:58,(files) `ui.yml`; T8.3 → `ui.yml`; ci-cd.md:25 | – |
| M29 | resolved | T2.6:28,49-53,70-72; T4.6:29; T7.1a:46-47 | (path drift, see N23) |
| M30 | resolved | SPEC:76-78; call-graph.md:108; R6.9 | – |
| M31 | resolved | T3.1a:70-71 S3, file list `infra/gpu/endpoints.yaml`; T5.1:21 | – |
| M32 | resolved | ci-cd.md:28,132-135; ADR-0005:85-88 (always-running `gate-required`) | (location conflict, see N6) |
| M33 | resolved | SPEC:492 (same-repo + `run-gate`, forks only via mirror) | – |

### A.2 `round1-technical.md` (10 blockers listed, 29 majors listed)

| id | status | evidence | remaining fix |
| --- | --- | --- | --- |
| S1 | resolved | SPEC:602-671 (significant **and** relevant, MDE, power table); ADR-0007:14-35; interfaces:396-406; T1.10:60 `pruefstand power` | – |
| S2 | resolved | SPEC:622-625; interfaces:439-445 (only gated slices change status) | – |
| S3 | resolved | T1.6:110 (σ_d × n × Gaussian/binary grid, type-I, power, CSV); SPEC:673-676; testing-strategy.md:70-86 | – |
| C1 | resolved | CLAUDE.md:44-46; ADR-0005:62-65; ci-cd.md:10,154; T0.5:48,61 | – |
| C2 | resolved | ADR-0005:75-81; ci-cd.md:155,160; T6.2a:57-63 | – |
| C3 | resolved | ADR-0006:128-130; ci-cd.md:122; interfaces:323,364-365 | – |
| C4 | resolved | ADR-0004:17-24; interfaces:329-335; T6.1 signing | – |
| C5 | resolved | ci-cd.md:163,168; SPEC:740-741; T6.1:47,62 `sanitise_run`; T2.6:49-53 held-out private | – |
| R1 | resolved | ci-cd.md:29-30; T9.1a:32-34; T0.5:64 | – |
| R2 | resolved | release.md:27 step 7 (`pruefstand-action` repo); T0.5 S12; T9.1b | – |
| S4 | resolved | interfaces:359-360; SPEC:607-609; T1.7:39-42; metric `error_rate` | – |
| S5 | resolved | SPEC:638-641; interfaces:407-408; T1.7:44,91 (Wilson rule per R1.7) | – |
| S6 | resolved | interfaces:391-392; T1.6:38; ADR-0007:20-21 (sign-test fallback per R1.8) | – |
| S7 | resolved | interfaces:418,439-441 (Holm per metric, BH informational only) | – |
| S8 | resolved | SPEC:188; T4.1:33-43 (`robust_pr` in PR tier) | – |
| S9 | resolved | SPEC:680-684; T6.3:34-46 | – |
| S10 | resolved | T7.2:27-28,54-55; SPEC:789-796 (prereg, matched rates, dose-response) | – |
| S11 | resolved | interfaces:126-127; T1.1:55-58; call-graph.md:137,149 | – |
| S12 | resolved | SPEC:650-652; ADR-0007:35; T6.2b:72 | – |
| J1 | resolved | SPEC:580-583; interfaces:294-295; T5.3:31 | – |
| J2 | resolved | SPEC:712-720; T5.4:38-44 (AC1, cluster bootstrap, human–human, discrimination) | – |
| J3 | resolved | interfaces:315-316,557-558; T5.2a:51,62,104 | (error-type drift, see N5) |
| J4 | resolved | SPEC:594-598; T5.2a:43-58,103; security.md:43 | (see N38) |
| G1 | resolved | gpu-cluster.md §5 (≤ 25 min); SPEC:525-526; T3.1b:44 | – |
| G2 | resolved | gpu-cluster.md:29-38; T6.2a:65-70 | – |
| G3 | resolved | gpu-cluster.md:20-22,43-53; SPEC:521 | – |
| G4 | partly | `serving` added: interfaces:73,153-154; T1.1:78; ADR-0006:18 | interfaces:614-615 also hashes `sorted(models.items())`, but T1.1:78, SPEC:376-377 and ADR-0006:18 do not → see N4 |
| G5 | resolved | gpu-cluster.md:26-27; SPEC:526; T6.2b:72 | – |
| C6 | partly | ADR-0005:85-88; ci-cd.md:132-135; security.md:30,35; T6.2b:53-60 | job location (`ci.yml` vs `gate-dispatch.yml`) and gated-path list disagree → see N6 |
| C7 | partly | one rule in ADR-0005:66-71 / ci-cd.md:157 | T6.2b:42-52 uses a different trigger set and a different `synchronize` policy → see N7 |
| C8 | resolved | T8.5:38-52; ci-cd.md:31 (by triggering run id, signed manifest) | – |
| C9 | resolved | T6.2a:44-48 (JIT config via App, keys outside runner user) | – |
| C10 | resolved | ADR-0017:28; docker.md:122; T8.5:42; T9.1a:62 | – |
| R3 | partly | T9.1a:36-43 (digest committed on release PR, `release.yml` does not rebuild) | release.md:27 step 6 and ci-cd.md:30 (`build-images` → `sign`) still say `release.yml` builds the images. Rewrite both to "verify digest from `action.yml`, re-sign, SBOM, attest" |
| D1 | partly | SPEC:436 hard_fail fixed; direction removed; budget names fixed | SPEC:438-444 `confidence` keys (N1); the "test that loads SPEC's example YAML" is not in any task — add to T1.2 tests |
| D2 | resolved | T1.5b:32-37,45,91 | (internal test contradiction, see N18) |
| D3 | resolved | SPEC:589-592; interfaces:145; T4.7b | – |
| D4 | resolved | DATA_LICENSES.md:39,63-71; SPEC:110-115; ADR-0015:14-15,28 | – |
| M1 (repro) | resolved | `TargetInfo.serving` inside `RunManifest.target` (interfaces:153-154,167); fingerprint includes serving | – |

### A.3 `round1-executability.md` (10 blockers #1–#10, 40 majors #11–#50)

| id | status | evidence | remaining fix |
| --- | --- | --- | --- |
| #1 T0.2↔T0.5 cycle | resolved | TASKS.md:21 T0.0; T0.2:6 "(repo exists on GitHub since T0.0)"; T0.2:120 `[NET]` | – |
| #2 T0.5 required checks | resolved | T0.5:31-33,43,55 (always-run only, later additions per task) | (name drift, see N9) |
| #3 T1.10 fixture | resolved | T1.10:41,62,98,110 (`examples/fake/mini/`, `min_clusters: 3`, sign-test p) | – |
| #4 T1.11 clusters | resolved | T1.11:25,33-35,S4 (`synthetic_v1`, 200 cases, ≥ 180 clusters, default policy) | – |
| #5 T2.6 real LLM | resolved | T2.6:6 (T5.1); TASKS.md:55 | – |
| #6 T4.3 Judge | resolved | T4.3:6,63; interfaces:528-529 (`check_support` via LLMClient) | – |
| #7 held-out canaries | resolved | T2.6:28,49-53,70-72,94-98,129,145-146 | (path drift, N23) |
| #8 T6.2 workflow names | resolved | T6.2b:25-27,70-72 match ci-cd.md §1 | – |
| #9 `stable_hash` | resolved | interfaces:176-178; T1.1:69-75,97,121 | – |
| #10 bootstrap / Windows | resolved | T0.0 prompt; CLAUDE.md:50-51; TASKS.md:21 | – |
| #11 parallel lanes | resolved | TASKS.md:155-159 | – |
| #12 shared files | resolved | CLAUDE.md:78-79; TASKS.md:161-162 | – |
| #13 make test/check | partly | CLAUDE.md:56,62 single definition; T0.2:101 `make check` unchanged | T0.1:57 `test` lacks `and not network`; deployment.md:55 lacks `not network` → copy CLAUDE.md:62 verbatim (N15) |
| #14 test roots | partly | T0.1:50 explicit testpaths + T0.1:54 `check_test_locations.py` | `tools/review_app/tests` (T4.7a:51,72), `infra/gpu/tests` (T3.1a:87), `scripts/docs/tests` (T9.2:59, T9.4:49), `scripts/report/tests` (T9.3:58) are outside testpaths and those tasks don't add them → N14 |
| #15 CLI package | resolved | see B1 | – |
| #16 SPEC refs | resolved | prompts now cite v2 sections (e.g. T1.10:17, T1.7:17, T5.1:18) | minor: T1.7:17 "§3.2 (hard fails)" should be §7.2 |
| #17 ADR paths | resolved | all referenced `docs/adr/*.md` exist | – |
| #18 T0.4 deploy | resolved | T0.4:30-32,49,67,87; T0.5 S6 | – |
| #19 T0.3 image | resolved | T0.3:34,57,95 (`pruefstand-smoke`) | – |
| #20 FakeTarget.info | resolved | T1.3:44-46,75; interfaces:242-244 | – |
| #21 T1.4 cache key | resolved | T1.4:34-40 ("interfaces.md wins"); T5.1:37-39 | – |
| #22 stale "flag" notes | resolved | T3.3:80; T1.4 no flag; remaining ones are pre-approved (T1.3:46, T1.6:46,98) | optional: delete the now-redundant "add to interfaces if missing" sentences |
| #23 T1.5 size | resolved | split T1.5a/T1.5b | – |
| #24 NIS2 key | resolved | T1.5a:89 `NIS2-RL`; T2.4:35 | – |
| #25 T1.6 type-I bound | resolved | T1.6:110 (Δ = 0, α + 0.01, reduced unmarked variant) | – |
| #26 T1.8 JudgePool/hard_fail/budget | resolved | T1.8:33-48,68-70,84 | – |
| #27 forbidden-strings rule | resolved | T1.11:85 | – |
| #28 fork test human | resolved | T1.12:66 (AI substitute), 104 `[HUMAN]` | – |
| #29 T2.1 live pins | resolved | T2.1:44-45 (format + 20 CELEX), 107, 124-126 `[NET]`, 132 | – |
| #30 T2.3 deps/paths | resolved | T2.3:6,25,53,100 | – |
| #31 T3.1 size/compose/endpoints | resolved | T3.1a:46-47,65-73; T3.1b | – |
| #32 T3.4/T3.5 GPU | resolved | T3.4:42,48,100 `--encoder hash`; T3.5:106 `[DOCKER]` | – |
| #33 `ReviewRound` | resolved | interfaces:535-537; T1.11:S3; T4.1 | – |
| #34 fixtures path | resolved | T4.1:6 `datasets/fixtures/v1`; T1.11 full manifest | – |
| #35 T4.2 deps/graph/pairs | resolved | T4.2:6,74-76; interfaces:479,525-526 | – |
| #36 T4.5 deps | resolved | T4.5:6 (T5.1, T3.1b) | – |
| #37 T4.6 curl needs stack | partly | T4.6:139 tagged `[GPU]` with fallback | fallback points to "T6.2b's re-index step"; the re-index is T6.2a S0 (T6.2a:75) (N35) |
| #38 T4.7 size | resolved | split T4.7a/T4.7b; `dataset-release.yml` → T9.1b | – |
| #39 T5.1 path/endpoints | resolved | T5.1:42-43,48,59 | (new gaps N12, N24) |
| #40 T5.2 fake judge | resolved | interfaces:216-217 `build_backend` `fake/`; T5.1:44-45,S3 | – |
| #41 T5.2 size | resolved | split T5.2a/T5.2b | – |
| #42 T6.1 duplicates | resolved | T6.1:45,57-58 (extend `core/fingerprint.py`, wire existing cache) | – |
| #43 T6.2 size/deps | resolved | split T6.2a/T6.2b; T6.2a:6,75 | – |
| #44 T6.3 | partly | T6.3:51-54,62,72,104 (no direction field, `test_cause.py`, SPEC vocabulary) | T6.3:84 keeps `MetricPolicy.confidence` (N1); T6.3:52-54,62 need T6.5 runs and M5, which only exist after T6.3 (N13) |
| #45 T6.5 metric/test | resolved | T6.5:77-79 (`ndcg_at_k`/`context_recall`, no `test_tenant_filter.py`) | – |
| #46 T7.1 size/command | resolved | split; T7.1a:123 `(cd /tmp/m08 && …)` | – |
| #47 T7.3 embedding/chunking | resolved | T7.3:31,58 | – |
| #48 T7.4 inputs | resolved | `results/_inputs/` in T5.4:68, T6.3:63, T7.2:69, T7.3:62, T7.4:19,29 | – |
| #49 T8.1 formats/ui.yml | resolved | interfaces:32; T8.1:55,58 | – |
| #50 T9.2 packaged fixture | resolved | interfaces:583; T9.2:34,56 | – |

---

## Task B — new consistency findings (introduced or exposed by the fixes)

| id | severity | file:line | problem | exact fix |
| --- | --- | --- | --- | --- |
| N8 | blocker | prompts/T6.2b-gate-workflows.md:113 vs docs/engineering/ci-cd.md:26,30,31, prompts/T0.4-docs-site.md:49 | T6.2b's static test asserts "only `build-images` has `id-token: write`" among public workflows, but `docs.yml` (created in T0.4, deploy job `pages: write` + `id-token: write`), `release.yml` and `deploy.yml` legitimately need it. T6.2b's Done-when `pytest tests/ci` cannot pass without breaking the Pages deploy. | T6.2b:113 → "`id-token: write` only in jobs of an allow-list: `build-images.yml/push-sign`, `docs.yml/deploy`, `release.yml/{publish-pypi,sign,attest}`, `deploy.yml/*`; never at workflow level". |
| N13 | blocker | prompts/T6.3-noise-thresholds.md:52-54,62 vs tasks/TASKS.md:102 (T6.5 depends T6.3), prompts/T6.5-mvp-demo-prs.md header, T7.1a (M5 is created there) | T6.3 S4 validates `likely_cause` "on runs of mutations M1, M5 and M8 from T6.5" and adds their patterns as fixtures, but T6.5 runs **after** T6.3, and T6.5 has no M5 (only reranker-off, whitespace, tenant-filter); M5 exists only from T7.1a. Dependency cycle; S4 and its Done-when line cannot be done. | Move S4 to T6.5 ("validate `likely_cause` on the three demo PRs; extend `test_cause.py`") and the M5 check to T7.2 (`likely_cause correct?` column already there, T7.2:68). T6.3:51-54 → "validation happens in T6.5/T7.2"; drop `test_cause.py` from T6.3 files and Done-when. |
| N1 | major | docs/architecture/interfaces.md:410 vs prompts/T1.2-config.md:45(d),68,84; prompts/T6.3-noise-thresholds.md:83-84; docs/spec/SPEC.md:438-444 | `MetricPolicy.confidence` exists in T1.2 (field + validator + test), T6.3 and the SPEC YAML, but interfaces §9 defines `MetricPolicy(max_drop, max_value)` only and states the CI level is `1 − 2α` (interfaces:419). With `extra="forbid"`, whichever side an implementer follows, the other breaks. | Pick interfaces (CI = 1 − 2α, technical S13): delete `confidence` from T1.2:68 and validator (d) ("`0 < alpha < warn_p < 1`" only) and its test (`confidence: 1.0` → error → replace with `MetricPolicy(confidence=0.9)` → extra-field error); delete from T6.3:84 and SPEC:438-444 (`{max_drop: 0.05}` etc.). |
| N2 | major | docs/architecture/interfaces.md:403 vs prompts/T1.6-gate-stats.md:43, prompts/T1.7-gate-policy.md:47,91, prompts/T1.9-report.md:32,74 | `decide` contract says "not gated → PASS (informational, never blocks)". T1.6 step 5 returns a non-gated FAIL as **WARN**; T1.7 expects informational slices to be "WARN (notable) or PASS" and its test asserts a `gated=False` WARN; T1.9 renders "gated=False WARNs" under notable drops. With the interfaces rule `notable_slices` would always be empty. | interfaces:403 → `# not gated -> never FAIL: a would-be FAIL or WARN is returned as WARN ("notable", never blocks); else PASS`. Keep T1.6/T1.7/T1.9 as they are. |
| N3 | major | prompts/T1.7-gate-policy.md:91,93; prompts/T1.11-fixtures-e2e.md:84 vs docs/spec/SPEC.md:697-705 | Tests reference SPEC §7.4 rules by number, but the numbering moved when `errors` became rule 3: a `context_recall` drop is rule 4 (`retrieval`), not "rule 3" (T1.7:91, T1.11:84); `drop_citations` is rule 6 (`citations`), not "rule 5" (T1.11:84, rule 5 = generation). Tests written as specified assert the wrong message. | Refer to codes, not numbers: T1.7:91 "cause = `retrieval`", T1.11:84 "cause = `retrieval`" and "cause = `citations`"; T1.7:93 "precedence (`security` over `errors`)". |
| N4 | major | docs/architecture/interfaces.md:181-184,614-615 vs prompts/T1.1-core-models.md:77-78,99-100,123; docs/spec/SPEC.md:375-377; docs/adr/0006-two-caches-fingerprints.md:18 | Fingerprint contracts differ: interfaces `corpus_version(manifest: CorpusManifest, date_tag: str)` vs T1.1 `corpus_version(date_tag: date, content_hashes: Mapping[str, str])`; interfaces `target_fingerprint(info, *, url: str, run_id)` hashing `models` + `serving` vs T1.1 `url: str \| None` hashing serving only (SPEC, ADR-0006 also omit `models`, but decisions.md:53 D36 includes them); `eval_fingerprint(splits: Sequence[Split])` vs T1.1 `Sequence[str]`. A model swap reported in `/v1/info.models` (M11) would not change T1.1's fingerprint. | Make interfaces authoritative and copy it: T1.1:77-78,99-100 → `corpus_version(manifest: CorpusManifest, date_tag: str)`, `target_fingerprint(info: TargetInfo \| None, *, url: str, run_id: str)` = `stable_hash(image_digest or git_sha, config_hash, corpus_version, sorted(models.items()), sorted(serving.items()))`, `splits: Sequence[Split]`; T1.1:123 add "changed `models.generator` → different fp"; SPEC:376 and ADR-0006:18 add `models`. call-graph.md:22,120 use the same signatures. |
| N5 | major | prompts/T1.2-config.md:44,53 (`core/models_family.py`, unknown → `"unknown"`); docs/adr/0009-litellm-providers.md:29-30; docs/architecture/interfaces.md:218,301,316; prompts/T5.1-llm-hardening.md:53 (`llm/families.py`, unknown → `ConfigError`); prompts/T5.2a-judges-prompts.md:93,104; docs/architecture/call-graph.md:21 | Two family tables (core regex table vs llm catalogue + lineage aliases) and three error types for a run-time family clash/unknown family: `GateInputError` (ADR-0009:29, interfaces:316), `ConfigError` (interfaces:301, T5.2a:104, call-graph:21 exit 2). Violates the R6.8 "single home" rule and ADR-0009. | One table: `llm/families.py` `family_of` (catalogue + aliases) is the only lookup; `core/models_family.py` stays as the *syntactic* sanity check for config load and its docstring says so (ADR-0009:29 → "config-time sanity regex in `core/models_family.py`; authoritative lookup `llm/families.py` `family_of`"). Error type: `ConfigError` everywhere (exit 2) → ADR-0009:29 and interfaces:316 change `GateInputError` → `ConfigError`. |
| N6 | major | prompts/T6.2b-gate-workflows.md:34,53-60,77 vs docs/engineering/ci-cd.md:22,28,58,132-135; docs/engineering/security.md:30; docs/spec/SPEC.md:499-501; docs/adr/0005-two-tier-ci.md:85-88 | `gate-required` is a job of `gate-dispatch.yml` in T6.2b but of `ci.yml` everywhere else. Gated paths also differ: T6.2b `apps/rag-demo/**, rag.yaml, datasets/**, pruefstand.yaml, infra/gpu/models.yaml`; others `apps/rag-demo/**, rag.yaml, packages/pruefstand/src/pruefstand/{metrics,judges,gate}/**`. | Choose `ci.yml` (it already runs on every PR with no environment): T6.2b:53,77 → "S2 `gate-dispatch.yml` (`dispatch`, `relabel-on-push`); S2b `gate-required` job in `ci.yml`", files list `.github/workflows/ci.yml (gate-required job)`. One path list (union) in ci-cd.md:132-133, SPEC:500-501, ADR-0005:86-87 and T6.2b:34: `apps/rag-demo/**`, `rag.yaml`, `datasets/**`, `pruefstand.yaml`, `infra/gpu/models.yaml`, `packages/pruefstand/src/pruefstand/{metrics,judges,gate}/**`. |
| N7 | major | prompts/T6.2b-gate-workflows.md:42-52,71-72 vs docs/engineering/ci-cd.md:28,39-40,68,76,157; docs/spec/SPEC.md:494; docs/adr/0005-two-tier-ci.md:66-71; docs/engineering/gpu-cluster.md:23 | Executor wiring disagrees: (a) nightly cron `0 0 * * *` UTC (T6.2b) vs `0 1 * * *` (ci-cd, SPEC); (b) ci-cd also gives the public `gate-dispatch.yml` a `0 1 * * *` cron while private `nightly.yml` has its own cron → double nightly; (c) `baseline-promote.yml` dispatch type `baseline-main` (ci-cd:39,68) vs `main-push` + `release` (T6.2b:71); (d) `gate-dispatch` triggers `labeled, synchronize` (ci-cd/ADR) vs `labeled, synchronize, opened, reopened` + `release: published` (T6.2b); (e) on `synchronize` ci-cd re-requires `gpu-gate` approval, T6.2b removes the label. | Make T6.2b the spec (it is the most detailed) and update ci-cd.md:28,39,40,68,76,157, ADR-0005:66-71 and SPEC:494 to: cron only in private `nightly.yml` `0 0 * * *` UTC (inside 01:00–06:00 Berlin, gpu-cluster.md:23); public `gate-dispatch.yml` triggers `pull_request` (`labeled, synchronize, opened, reopened`), `push: main`, `release: published`; dispatch types `gate-pr`, `main-push`, `release`; `synchronize` removes `run-gate` (re-label + env approval needed). |
| N9 | major | prompts/T0.5-github-setup.md:43,55 vs docs/engineering/ci-cd.md:22-27,129-131; prompts/T0.2-ci-pipeline.md:85,99; prompts/T1.12-github-action.md:62; prompts/T8.1-dashboard-scaffold.md:58 | Required-check names disagree, the exact failure class of round-1 #2: T0.5 S2 requires `file-size, test-slow, test-integration, e2e, schemas-fresh, workflow-guards` (not in ci-cd §5 list, and `workflow-guards` is not in the ci-cd `ci.yml` job list) but omits `zizmor`; T0.5 S7 adds `compose-config, compose-lint` (ci-cd: `trivy`), `selftest` (ci-cd: `action-selftest`; T1.12 names the job `selftest`), `ui-lint, ui-typecheck, ui-unit` (ci-cd: a `ui` summary job that T8.1 never creates). | ci-cd.md §1.1/§5 becomes the copy of T0.5: ci.yml jobs add `workflow-guards`; required now = all ci.yml jobs of T0.2:99-100 + `codeql`, `gitleaks`, `pip-audit`, `zizmor`; later: `hadolint`, `build`, `trivy`, `compose-config` (T0.3), `docs-build` (T0.4), `selftest` (T1.12), `ui-lint`, `ui-typecheck`, `ui-unit`, `types-fresh` (T8.1), `playwright` (T8.3), `gate-required` (T6.2b). Fix T0.5:43,55 (+`zizmor`, `trivy`; `compose-lint` only if it is a job), T0.2:85 and ci-cd.md:22-27,129-131 to this one list. |
| N10 | major | prompts/T0.5-github-setup.md:62-63 vs prompts/T6.2a-gate-executor.md:51-55; prompts/T6.2b-gate-workflows.md:60,72 | App `pruefstand-gate-bot` permissions: T0.5 gives public `pull_requests, statuses: write, contents: read`, private `contents: write, actions: read`; T6.2a needs public `issues: write` (nightly issue, T6.2b:72) and `actions: write` (re-run `gate-required`, T6.2b:60). Following T0.5 makes both flows fail. | T0.5:62 → public repo `pull_requests: write, statuses: write, issues: write, actions: write, contents: read`; private repo `contents: write` (token only in env `baseline`). |
| N11 | major | prompts/T6.1-baseline-store-cache.md:62,98 (`sanitise_run(run, canaries: CanaryRegistry)`) vs prompts/T1.1-core-models.md:41 (`core.models.attacks` owned by T2.6); tasks/TASKS.md:97,159 | T6.1 depends only on T1.10 and is in the parallel lane right after T1.10, but `CanaryRegistry` is created in T2.6 (which needs T5.1 → T3.1b → GPU). T6.1 cannot type or test `sanitise_run`. | Move `Canary`, `CanaryRegistry` (data model only, interfaces:503-506) into T1.1 (T1.1:41 → `core.models.attacks` `Canary`, `CanaryRegistry`: T1.1; `make_canary_token`/`plant_canaries` stay in T2.6); T2.6:86 "(already created in T1.1)". |
| N12 | major | prompts/T5.1-llm-hardening.md:49 vs prompts/T6.1-baseline-store-cache.md:58; tasks/TASKS.md:87,97; docs/architecture/interfaces.md:322 | T5.1 S4 "Wire `DiskKVCache` … into `LLMClient`", but `DiskKVCache` is in `store` and created in T6.1, which T5.1 does not depend on (T5.1: T1.4, T3.1b) and `llm` may not import `store`. | T5.1:49 → "`LLMClient` takes any `KVCache`; test with an in-memory and a `diskcache`-backed test double. Production wiring of `store.DiskKVCache` (namespace `llm`) is done by `pipeline` in T6.1." Add to T6.1 S2: "pipeline builds `DiskKVCache('llm')` for `LLMClient`". |
| N14 | major | prompts/T0.1-repo-scaffold.md:50,54 vs prompts/T4.7a-review-tool.md:51,72; prompts/T3.1a-gpu-cluster-services.md:87; prompts/T9.2-readme-quickstart.md:59; prompts/T9.3-technical-report.md:58; prompts/T9.4-blog-linkedin.md:49 | T0.1 fixes explicit testpaths and adds `check_test_locations.py` (fails `make check` for any test outside them). `tools/review_app/tests`, `infra/gpu/tests`, `scripts/docs/tests`, `scripts/report/tests` are outside and those tasks never add them (T4.7a and T3.1a even claim "collected by make test"). | T0.1:50 testpaths → `["packages/pruefstand/tests", "apps/rag-demo/tests", "scripts", "tests", "benchmarks/tests", "experiments", "tools", "infra"]` (directory prefixes cover all sub-`tests/`); delete the per-task "testpaths += …" lines in T5.3:60, T6.2a:98, T6.2b:97, T7.1a:93, T7.4:62, T9.1b:79. |
| N18 | major | prompts/T1.5b-deterministic-metrics.md:37 vs :91 | The semantic-leak rule ("every content word of the normalised fact occurs in the text **in order**, gaps ≤ 3 tokens") cannot make the required test pass: "Bei Bergmann gilt eine 47-tägige Kündigungsfrist" lacks `Rahmenvertrag`, `Firma`, `beträgt` and has a different order. The session will either fail or invent a rule. | Define the fact's **key terms** explicitly in the canary (`Canary.forbidden_answer` = e.g. `"Bergmann 47 Tag"` from T2.6) and match: all key terms present (stem prefix ≥ 4, number words normalised), any order, within a 12-token window. T1.5b:37 rewrite accordingly; T2.6 writes `forbidden_answer` as key terms. |
| N15 | minor | prompts/T0.1-repo-scaffold.md:57; docs/architecture/deployment.md:55 vs CLAUDE.md:62 | `make test` marker set lacks `and not network`. | Copy CLAUDE.md:62 verbatim into both. |
| N20 | minor | prompts/T3.1a-gpu-cluster-services.md:73,90 (`test-gpu`); T8.1:58 (`ui-check =`); T8.3:55 (`ui-check +=`); T7.4:57; T3.7:74 vs CLAUDE.md:70,72,76-77 | CLAUDE says T0.1 creates **all** targets and later tasks never redefine them, yet these tasks (re)define `test-gpu`, `ui-check`, `experiments`. | Either T0.1 creates them as delegating stubs (`ui-check: ; $(MAKE) -C apps/dashboard check` / `experiments: ; uv run python experiments/run_all.py`) and the tasks only add the delegated files, or CLAUDE.md:76-77 adds "except `ui-check` (T8.1/T8.3) and `experiments` (T7.4), which extend via `mk/*.mk`". Drop `test-gpu` from T3.1a S5. |
| N21 | minor | prompts/T6.1-baseline-store-cache.md:64 vs docs/architecture/interfaces.md:574-576 | `baseline export-public` and `gate --from-store --ref main\|release` are not in the CLI contract (only `baseline promote --ref main`, `--from-store` without `--ref`). T8.5:47 also uses `export-public`. | interfaces:574-576 → add `--ref main\|release` to `gate`, `baseline promote --ref main\|release`, `baseline export-public --run … --out …`. |
| N22 | minor | docs/architecture/interfaces.md:322 vs :362; docs/adr/0006-two-caches-fingerprints.md:14-19; docs/architecture/data-model.md:288; T5.1:49; T6.1:58 | LLM cache namespace is `llm` (interfaces §7, T5.1, T6.1) and `judge` (interfaces §8 text, ADR-0006, data-model, ci-cd.md:122). | Use `llm` everywhere (it also caches datagen/perturb calls); fix interfaces:362, ADR-0006 table, data-model.md:242,288, ci-cd.md:122. |
| N23 | minor | prompts/T2.6-private-docs-canaries.md:51 vs prompts/T7.1a-mutations-core.md:47 | Held-out set path: `datasets/private/heldout/canaries_heldout.json` vs `datasets/private/canaries_heldout.jsonl`. | T7.1a:47 → `datasets/private/heldout/canaries_heldout.json` (via `PRUEFSTAND_HELDOUT_DIR`). |
| N24 | minor | prompts/T5.1-llm-hardening.md:21; prompts/T5.4-judge-calibration.md:31 | Both read `infra/gpu/models.lock.yaml` "(T3.1b)", which no task creates; T3.1b pins into `infra/gpu/models.yaml` (T3.1b:60-61). | Replace `models.lock.yaml` with `infra/gpu/models.yaml` (pinned, `provisional: false`). |
| N25 | minor | docs/architecture/call-graph.md:22,68,70,120 vs interfaces.md:181-184,432-433; prompts/T1.10-pipeline-cli.md:58 | call-graph drift: `target_fingerprint(info, corpus_version)`; `evaluate_gate(baseline, candidate, policy, rng)` without `directions`; `GateInputError, exit 2` (T1.10: any other `PruefstandError` → 3); `corpus_version(manifest)`. | Use the interfaces signatures; GateInputError → "exit 3" (or add `GateInputError → 2` to T1.10:58 and interfaces:570 — pick one). |
| N26 | minor | docs/spec/SPEC.md:647-648 vs docs/architecture/interfaces.md:443-444 | SPEC's overall-status sentence omits "absolute-check `warn`" as a WARN source. | SPEC:647-648 → "else `warn` if any gated `warn`, any absolute-check `warn` or `unsupported_config`". |
| N27 | minor | prompts/T1.9-report.md:74 vs docs/spec/SPEC.md:729-731 | Snapshot row has 6 cells (`… \| 0.04 \| FAIL \|`), SPEC §7.6 table has 7 (δ and MDE). | T1.9:74 → `\| Context recall \| 0.86 \| 0.79 \| −0.07 (−0.10, −0.04) \| 0.05 \| 0.04 \| FAIL \|`. |
| N28 | minor | docs/engineering/ci-cd.md:158; docs/adr/0005-two-tier-ci.md:73-74 vs prompts/T6.2b-gate-workflows.md:63-64 | Mirror deny list: ci-cd/ADR include `scripts/mirror_fork_pr.sh`, omit `infra/gate-executor/**`; T6.2b the reverse. | All three: `.github/**`, `infra/runner/**`, `infra/gate-executor/**`, `action/**`, `scripts/mirror_fork_pr.sh`. |
| N29 | minor | "Unblocks" rows: T5.1:7 (T6.1), T1.12:7 (T6.2b, T9.1b), T4.7b:7 (T6.2b), T1.11:7 (T8.1), T2.1:7 (T4.6, T4.7a), T3.4:7 (T4.6, T6.2a) vs tasks/TASKS.md | Unblocks lists name tasks whose TASKS "Depends" does not include this task. | Derive every Unblocks row from TASKS reverse dependencies (script), or drop the column. |
| N30 | minor | tasks/TASKS.md:36 vs docs/architecture/interfaces.md:279 | TASKS T1.5a names `match_key`; contract is `citations_match`. | TASKS:36 → `citations_match`. |
| N31 | minor | prompts/README.md:30 vs prompts/T0.3-docker-compose.md:24,46 | Index says "image build + Trivy in `ci.yml`"; T0.3 creates `build-images.yml`. | README:30 → "… in `build-images.yml`". |
| N32 | minor | docs/decisions.md:15 (D5) | Still "ephemeral self-hosted A40 runner for the real gate, trusted PRs or `run-gate` label only", no private executor. | Append "(superseded by R2: runner only in private `pruefstand-gate`, see D3x/ADR-0005 rev.)". |
| N33 | minor | prompts/T9.1a-release-pipeline.md:33,47 vs prompts/T0.5-github-setup.md:64,74 | App name `pruefstand-release-bot` vs `pruefstand-release`; env `testpypi` not in T0.5 environment list. | One name (`pruefstand-release`); T0.5:74 environments + `testpypi`. |
| N34 | minor | docs/engineering/ci-cd.md:32 vs prompts/T9.1b-marketplace-hf.md:43,96 | `dataset-release.yml`: tag `dataset-v*` + dispatch vs dispatch only. | Pick dispatch-only and fix ci-cd.md:32 and :136 (`dataset-v*` tag rule). |
| N35 | minor | prompts/T4.6-attacks.md:139 | Fallback "leave this to T6.2b's re-index step"; re-index is T6.2a S0 (T6.2a:75). | → "T6.2a S0". |
| N36 | minor | docs/engineering/ci-cd.md:28 vs docs/adr/0005-two-tier-ci.md:70; prompts/T6.2b-gate-workflows.md:49 | Dispatch payload includes `image_digest` only in ci-cd. | Add `image_digest` to ADR-0005:70 and T6.2b:49 (the executor needs it for pull-by-digest). |
| N37 | minor | docs/spec/SPEC.md:188, prompts/T4.1-dataset-manifest-splits.md:39-43 vs interfaces:416-417 | `robust_pr` has 30 bases, so each gated `perturbation` slice has ≤ 30 clusters; if two bases share a source document (cluster_id), the slice is always `INSUFFICIENT_DATA`. | T4.1: require 30 distinct `cluster_id`s among `robust_pr` bases (test), or raise to 40 bases. |
| N38 | minor | docs/architecture/interfaces.md:313-314 vs docs/spec/SPEC.md:596; prompts/T5.2a-judges-prompts.md:43-46 | Interfaces show static `<frage>`/`<antwort>` blocks; SPEC/T5.2a use nonce delimiters, and T5.2a derives the nonce from the case seed (predictable, weakening J4). | interfaces:313 → "blocks with a per-call nonce (`<antwort-<nonce>>`)"; T5.2a:46 → nonce = `stable_hash(secret_salt_env, case.id)` so caching stays stable but the nonce is not derivable from public data. |
| N40 | minor | docs/spec/SPEC.md:719-720 vs prompts/T5.4-judge-calibration.md:44 | T5.4 adds "discrimination ≥ 0.90" to the selection rule; SPEC does not. | SPEC:719 add "and discrimination ≥ 0.90". |
| N41 | minor | docs/engineering/ci-cd.md:110 vs prompts/T8.5-deploy-cd.md:68,81 | Rollback doc `docs/runbooks/rollback.md` vs `docs/engineering/deploy-runbook.md`. | ci-cd.md:110 → `docs/engineering/deploy-runbook.md`. |
| N42 | minor | prompts/T6.2b-gate-workflows.md:82,90; prompts/T7.4-make-experiments.md:50 vs docs/engineering/ci-cd.md:22-23 | T6.2b adds an `actionlint + zizmor` job to `ci.yml` (zizmor already in `security.yml`, T0.2 S2); T7.4 adds `experiments-check` to `ci.yml`; neither is in ci-cd's `ci.yml` job list. | T6.2b S7 → extend `workflow-guards` with the private-workflow dir instead of a new job; add `experiments-check` (T7.4) to ci-cd.md:22. |
| N43 | minor | prompts/T6.3-noise-thresholds.md:87 vs docs/architecture/interfaces.md:398-399 | `power_estimate(..., m: int)` without default and without `true_drop`. | Copy interfaces:398-399. |
| N44 | minor | prompts/T1.2-config.md:45(a) vs docs/architecture/interfaces.md:557 | Validator "(a) if `generator_family` set …" implies optional; contract makes it required (`generator_family: str`). | T1.2:45(a) → "`generator_family` is required; every judge family must differ from it"; add test "missing `generator_family` → error". |

(N16, N17, N19, N39 were merged into Task A rows M26, R3, D1 and J4 to avoid double counting; ids kept unique.)

Counts: blocker 2 (N8, N13) · major 13 (N1–N7, N9–N12, N14, N18) · minor 25.
