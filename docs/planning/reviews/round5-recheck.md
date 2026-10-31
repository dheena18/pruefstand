# Round 5: recheck of all open review findings

Scope: every finding in `round2-verify.md` (Task A rows marked "partly" and all Task B rows), `round2-expert.md`,
`round3-final.md` and `round4-verify.md`, checked against the current files (everything outside
`docs/planning/`; `SPEC-v1-original.md` ignored). Binding order: round1 < round2 < round4 resolution, plus
`docs/decisions.md` D1–D90 without the `[superseded]` rows. Line numbers are for the files after this round.

Status values: **fixed** = already correct before this round; **fixed now** = was not fixed or only partly fixed,
and this round edited it; **obsolete** = a later binding decision removed the premise.

## round2-verify.md, Task A (the 15 "partly" rows)

| Finding | Status before | Action (file:line) |
| --- | --- | --- |
| A M3 | obsolete | Q1.8/D59 keeps `MetricPolicy.confidence` (display CI only), and interfaces.md:442 defines it, so SPEC:459-465 and T1.2:78 are now valid |
| A M8 | fixed | components.md lists all 7 ADR-0016 contracts verbatim, including `siblings-independent` and `llm.backends.litellm` |
| A M12 | fixed | data-model.md:246 uses the 8-part key |
| A M14 | obsolete | Q2.1/D61: there is no `gate-dispatch.yml`, so the trigger-rule conflict is gone. The nightly cron is `0 0 * * *` everywhere |
| A M18 | fixed | no "rule N" references remain; tests assert codes (D58) |
| A M26 | partly → **fixed now** | layout was already `baselines/<eval_fp>/<ref>/`. Unified the manifest name to `manifest.json`: T6.1:34,35,58,103,104. Unified the error type for a sha256 mismatch to `StoreError`: ADR-0004:46, security.md:29 |
| A G4 | fixed | T1.1:81, SPEC:396, ADR-0006:18 include `sorted(models.items())` |
| A C6 | obsolete | Q2.5: there is no `gate-required` job; `pruefstand/gate` comes from the App; one gated-path list in ci-cd.md §5 |
| A C7 | obsolete | Q2.1: no dispatch workflow and no label/`synchronize` policy in the public repo |
| A R3 | obsolete | the "digest before tag" design was dropped (expert F34). ADR-0017, release.md:27 and SPEC:526 build images on the tag |
| A D1 | fixed | `confidence` is kept (Q1.8). T1.2:99 already loads the SPEC §5.6 example YAML in a test |
| A #13 | partly → **fixed now** | T0.1:64 now has `and not live` (verbatim CLAUDE.md:70). T0.1:55 adds the `live` marker (`--strict-markers`). deployment.md:53: replaced the non-existent `make live` |
| A #14 | fixed | D71 testpaths cover `tools/*/tests`, `infra/gpu/tests`, `scripts/*/tests` (T0.1:56) |
| A #37 | fixed | T4.6:139 points to T6.2a S0 |
| A #44 | fixed | `confidence` is kept (Q1.8). T6.3 no longer needs T6.5/M5 (D85: real bug switches) |

## round2-verify.md, Task B

| Finding | Status before | Action (file:line) |
| --- | --- | --- |
| N1 | obsolete | Q1.8/D59: `confidence` exists in interfaces.md:442 |
| N2 | fixed | interfaces.md:434: not gated → always PASS (Q1.2/D52) |
| N3 | fixed | cause codes only (D58) |
| N4 | fixed | T1.1:81,102 use the interfaces signatures, including models and serving |
| N5 | fixed | one table `model_families.yaml`; `ConfigError` (D74) |
| N6 | obsolete | no `gate-required` (Q2.5); one path list in ci-cd.md:180-182 |
| N7 | obsolete | no public dispatch (Q2.1); nightly cron `0 0 * * *` in the private `nightly.yml` only |
| N8 | fixed | `id-token` allowlist (D68) in T0.2:82,122 and ci-cd.md:33 |
| N9 | fixed | aggregator checks per D66 (T0.5:35-43, ci-cd.md:175-176) |
| N10 | obsolete | Q2.4/D64: a single App `pruefstand-bot` with fixed permissions; no dispatch or rerun |
| N11 | fixed | `CanaryRegistry` is in T1.1:42,70 (D76) |
| N12 | fixed | `DiskKVCache` from T1.8; T5.1:64 is wired by the pipeline (D75) |
| N13 | fixed | T6.3 uses real bug switches (D85); real-mutation validation is in T7.2:89 |
| N14 | fixed | D71 testpaths (T0.1:56) |
| N15 | **fixed now** | T0.1:64 marker set (same edit as A #13); deployment.md:53 |
| N18 | fixed | T1.5b:39 uses the `re:` semantic canary regex and the test at :94 matches it |
| N20 | **fixed now** | CLAUDE.md:87 states the exceptions (`ui-check` T8.1/T8.3, `experiments` T7.4) and allows appending new task targets. T0.1:63,64,69 creates all §3 targets (added `test-live`, `cassettes`, `experiments` stubs). T3.1a:75,92: `test-gpu` is no longer redefined. T3.7:75 appends a variable only |
| N21 | **fixed now** | interfaces.md:620 `gate ... --from-store [--ref main\|release]`; :622 `baseline promote --ref main\|release` and `export-public` |
| N22 | **fixed now** | interfaces.md:390 namespace `judge` → `llm` (the rest was already `llm`) |
| N23 | fixed | T7.1a:56 uses the T2.6 path |
| N24 | fixed | no `models.lock.yaml` remains |
| N25 | fixed | call-graph.md:21,69 use the interfaces signatures; `GateInputError` → exit 3 (call-graph.md:67,102) |
| N26 | fixed | SPEC:709-710 includes the absolute-check `warn` |
| N27 | fixed | T1.9:80 has 7 cells |
| N28 | fixed | the same deny list in T6.2b:52-53, ADR-0005:35-36, ci-cd.md:213, security.md:27 |
| N29 | partly → **fixed now** | corrected the six rows the finding names to the TASKS reverse dependencies: T5.1:7, T1.12:7, T4.7b:7, T1.11:7, T2.1:7, T3.4:7. `_TEMPLATE.md:7` now says Unblocks is informational and TASKS "Depends" is authoritative. Other prompts still list transitive dependents, which is harmless |
| N30 | fixed | TASKS uses `citations_match` (no `match_key` left) |
| N31 | **fixed now** | prompts/README.md:31 → `build-images.yml` |
| N32 | fixed | decisions.md:15 D5 is marked superseded |
| N33 | fixed | one App name `pruefstand-release`; `testpypi` env in T0.5:94 |
| N34 | fixed | `dataset-release.yml` is `workflow_dispatch` only everywhere |
| N35 | fixed | T4.6:139 "T6.2a S0" |
| N36 | obsolete | no dispatch payload (Q2.1). The executor reads the digest from the `pruefstand/image` status |
| N37 | fixed | 40 bases from 40 distinct `cluster_id`s (T4.1:39,44; D55) |
| N38 | partly → **fixed now** | T5.2a:43-46 already used a keyed-HMAC nonce. interfaces.md:340-341 now shows the nonce delimiters |
| N40 | fixed | SPEC:805 has discrimination ≥ 0.90 |
| N41 | fixed | ci-cd.md:153 → `deploy-runbook.md` |
| N42 | fixed | `experiments-check` is in the ci-cd.md:41 job list; T6.2b adds no extra job |
| N43 | fixed | T6.3:104 = interfaces.md:429 |
| N44 | fixed | T1.2:54 `generator_family` is required, with a test at :98 |

(N16, N17, N19, N39 were merged into A M26, R3, D1, J4 by round 2; they are not counted separately.)

## round2-expert.md

| Finding | Status before | Action (file:line) |
| --- | --- | --- |
| F1 | fixed | no `.review/` reference in prompts (D77) |
| F2 | fixed | one Holm family (D51) |
| F3 | partly → **fixed now** | D56 and T6.3 already use the detectable drop. decisions.md:153 pinned row: "MDE ≤ δ" → "detectable drop ≤ 2δ, D56" |
| F4 | fixed | `robust_pr` = 40 bases, ≥ 40 clusters (D55) |
| F5 | fixed | codes only (D58) |
| F6 | fixed | D52 |
| F7 | fixed | D53, SPEC:698-702. Cleanup: T1.7:83-84 dropped a stale "list under Interface changes" instruction, because SPEC/interfaces already say this |
| F8 | partly → **fixed now** | the sims/B pair now matches T1.6:114 and D57 (4 000 / B 400, ≤ 300 s, reduced unmarked cell): testing-strategy.md:41,104,113, ADR-0007:44; the CSV path is `build/simulation/power_curves.csv` |
| F9 | fixed | T1.7:108,143 `notable_slices` |
| F10 | fixed | T1.7:71 `r.se`; `mde=None` for informational slices |
| F11 | fixed | T1.7 fixtures F0/F1 exact; perturbation `None` is not a slice; absent metric = stable (T1.7:89) |
| F12 | fixed | no-op generator specified (T1.7:193, testing-strategy.md:106-109) |
| F13 | fixed | HTTPS remote + `gh auth setup-git` (T0.0:75,99) |
| F14 | fixed | T0.0:59-84 |
| F15 | fixed | Copilot is optional everywhere (D67) |
| F16 | fixed | `.gitattributes` before `git add -A` (T0.0:94-97) |
| F17 | fixed | importlib mode, no `__init__.py` (D71) |
| F18 | partly → **fixed now** | T0.1:64 claimed to be verbatim but lacked `not live`; fixed (same edit as A #13) |
| F19 | fixed | T0.1:70 `git diff --exit-code -- schemas/` |
| F20 | fixed | Typer callback (T0.1:50) |
| F21 | fixed | `[NET]` tags (T0.1:126,132); T0.2:18 section numbers match ci-cd.md |
| F22 | fixed | D69, T0.1:135 |
| F23 | fixed | 0 approvals (D66) |
| F24 | obsolete | Q2.1/D61: no public-repo secret, pull-based executor |
| F25 | partly → **fixed now** | D62 was already in place. ci-cd.md:183-184: repaired a truncated sentence (" . A PR …"), so it now reads "main's package, `pruefstand.yaml` and dataset (never the PR's copies, D62)" |
| F26 | fixed | one gated-path list (ci-cd.md:180-185, per Q2.5) plus the note that gate code is validated by tier 0/1/nightly |
| F27 | obsolete | Q2.5: `pruefstand/gate` from the App is the required check; `gate-required` is deleted |
| F28 | fixed | candidate has no GPU/CDI (T6.2a:55,128; gpu-cluster.md:139) |
| F29 | partly → **fixed now** | ci-cd.md:211 now uses the T6.2a:75 identity regexp (`refs/(heads/.+\|pull/[0-9]+/merge)`); "origin only" is stated in both |
| F30 | obsolete | no dispatch; id-token allowlist (D68) |
| F31 | fixed | T0.6 feasibility (D79, D90) |
| F32 | partly → **fixed now** | the unattended bench path was already in T7.2:64-70. T7.2:11 GPU estimate "~8–12 h" → "~20–35 h (44 PR-tier runs × 25–45 min + re-indexes)" |
| F33 | fixed | A/A replay arm (T7.2:52-55); `directions` in the signature (T7.2:109) |
| F34 | fixed | single package, `include-component-in-tag: false`, build on tag (T9.1a:72, ADR-0017:14-16) |
| F35 | fixed | T9.1a:111 extra index |
| F36 | fixed | D73; T1.1:81 |
| F37 | obsolete | Q1.8 keeps `confidence`. `max_error_rate` (baseline validity) and `error_rate.max_value` (candidate absolute check) have distinct roles in interfaces.md:454 |
| F38 | fixed | `NDArray` in both (interfaces.md:422, T1.6:90) |
| F39 | fixed | repeats estimate σ_d only (SPEC:751, T6.3:45) |
| F40 | partly → **fixed now** | ci-cd.md:44 and testing-strategy.md:50,156 already made Lighthouse/WebKit/mutmut nightly and informational. Prompts now match: T8.3:23-24,44,86 (PR = Chromium + mobile + axe; WebKit, visual regression and Lighthouse run nightly); T7.4:39-40,50,60 (mutmut in private `nightly.yml`, informational until M7; `ci.yml` has no schedule). TASKS.md:189 review budget 18 h → 30 h (sum ≈ 53 h, matches SPEC:910 "≈ 55") |

## round3-final.md

| Finding | Status before | Action (file:line) |
| --- | --- | --- |
| F1 | fixed | T9.3 has no "Holm per metric" |
| F2 | partly → **fixed now** | REVIEW.md:98 "revised in round 1" → "rounds 1–2" |
| F3 | fixed | SPEC:744-745 ≤ 0.12 |
| F4 | fixed | testing-strategy.md:109 ≤ 0.12 |
| F5 | fixed | T3.1b:44 440 |
| F6 | fixed | _review.md:4-5 |
| F7 | fixed | _session-start.md:9 |
| F8 | fixed | _session-start.md:22 |
| F9 | fixed | T5.1:6 = TASKS |
| F10 | fixed | T8.5:6,110; TASKS.md:137 |
| F11 | fixed | T9.2:6,19,41 |
| F12 | partly → **fixed now** | CLAUDE.md:39-40 and D71 were already aligned with T0.1:56. T6.2a:98: the false "`infra/*/…/tests` pattern" claim now says to append `infra/gate-executor/orchestrator/tests` |
| F13 | fixed | TASKS.md:44 `CauseCode` comes in T1.7 |
| F14 | partly → **fixed now** | ADR-0017:14 already named the App. Added the App name and limits to SPEC:526, ci-cd.md:49, release.md:23 |
| F15 | fixed | `[superseded]` markers on D22–D33 |
| F16 | fixed | no literal `.review/` in T0.0 |

## round4-verify.md

| Finding | Status before | Action (file:line) |
| --- | --- | --- |
| F1 | fixed | one name, `live-e2e / gate` (D66), in all docs and prompts (T1.12:59 aggregator job `gate`) |
| F2 | fixed | `live-baseline` everywhere |
| F3 | fixed | budget ≤ 30 min, hard cap `timeout-minutes: 40` (D81) everywhere, including T0.2:89 and T1.12:60 |
| F4 | fixed | ADR-0005:19,50; SPEC:352-354 |
| F5 | partly → **fixed now** | T1.12:48,56 and ci-cd.md:64 already used push + schedule. T1.12:84 still said "push:main"; now it says "push or nightly schedule" |
| F6 | fixed | one set of `answer_*_de_v1.txt` names |
| F7 | fixed | `injection_guard: off` (T7.1a:71) |
| F8 | fixed | SPEC:512 `top_k` (M10) |
| F9 | fixed | T4.1:59 CC BY 4.0 |
| F10 | fixed | T8.4:56 |
| F11 | fixed | T1.2:49 `0.0` + `max_requests_per_run` |
| F12 | fixed | `llm/policy.py` only, `PolicyViolation(LLMError)` (T1.4:57, T5.1:55-56) |
| F13 | fixed | T5.1:124,130 |
| F14 | partly → **fixed now** | SPEC, sequences and call-graph were already fixed. prompts/README.md:70 "Human review loop" → "20 % model review + owner spot-check" |
| F15 | fixed | sequences.md §6 |
| F16 | fixed | D41 is marked superseded; SPEC has no "Humans label" |
| F17 | fixed | no Slurm deliverables; T6.2a:83 Podman/Apptainer |
| F18 | fixed | no "frontier"; T3.6:55 `premium.yaml` is disabled by default |
| F19 | partly → **fixed now** | T1.10:81 and T7.1b:64 were fixed. T10.1:58 `run_eval` gets `"bench"` |
| F20 | fixed | T1.1:109, T8.1:84, call-graph.md:254 |
| F21 | fixed | TASKS.md:37, T0.5:41,102 |

## Counts

| Source | Findings | Fixed already | Fixed now | Obsolete | Could not fix |
| --- | --- | --- | --- | --- | --- |
| round2-verify Task A (partly rows) | 15 | 8 | 2 | 5 | 0 |
| round2-verify Task B | 40 | 28 | 7 | 5 | 0 |
| round2-expert | 40 | 29 | 7 | 4 | 0 |
| round3-final | 16 | 13 | 3 | 0 | 0 |
| round4-verify | 21 | 18 | 3 | 0 | 0 |
| **Total** | **132** | **96** | **22** | **14** | **0** |

No fake (FakeLLM / FakeTarget / `Degradation` / `target.type: fake`) is relied on anywhere, so every
fake-related item is either fixed or obsolete under V1/D80.
