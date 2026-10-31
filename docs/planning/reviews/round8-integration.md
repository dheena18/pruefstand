# Round 8 integration log

Integrator pass after the six parallel fixers applied `round8-resolution.md`. Binding owner decisions
1–8 applied across the pack (outside `docs/planning/`). New decision rows: `docs/decisions.md` D141–D145.

## 1. Nightly judge = gemma (D141)

- Family plan now: generator `qwen`; PR judge `mistral` (`gemma` if it fails calibration); nightly judge
  `gemma` 27B-class int4 on **one** A40; datagen `llama` 70B-class (datagen batch jobs only); tier-1 judge a
  non-qwen GitHub Models model.
- Night mode: phase A day services → `switch-mode.sh night` stops `vllm-generator`, starts
  `vllm-nightly-judge` (GPU0, util 0.80, profile `gpu-night`, host :8103); PR judge stays on GPU1.
  New **datagen mode** (`switch-mode.sh datagen`, profile `gpu-large`, `vllm-large` TP=2) only for
  T4.2/T4.5/T2.6 batch jobs and the optional RQ2 70B arm.
- Nightly judge is core (no "optional 70B tier"); `judge_fallback` stays for an unavailable nightly judge.
- Self-preference limitation removed (SPEC §6.3, gpu-cluster §2, T5.4, T9.3); only the optional RQ2 70B
  `llama` arm shares the datagen family and is reported separately.
- Files: interfaces.md (core.data, RunManifest/LLMPolicyConfig comments), SPEC §5.6/§6.2/§6.3/§7.5 RQ2/§12,
  gpu-cluster.md (§1–§5, §8, no-go fallback), docker.md (profile `gpu-night`, port table), deployment.md,
  sequences.md, data-model.md, ADR-0009, ci-cd.md, ai-workflow.md, DATA_LICENSES §5 (Gemma Terms of Use +
  Prohibited Use Policy, **verify**), decisions (D38/D78/D112 marked, D141, pinned rows), TASKS (T1.2,
  T3.1a, T6.2b rows, optional-scope note), prompts T0.6, T1.2 (`plan.judge_nightly: gemma`), T3.1a
  (role `nightly_judge`, `gpu-night`, make targets), T3.1b, T4.2, T5.1/T5.2a (now use T1.2's `plan:` block,
  not a second `roles:` block), T5.2b, T5.4, T6.2b, T9.3, `_session-start.md`; REVIEW.md history notes.

## 2. `refusal_correct` δ = 0.10 (D142)

SPEC §5.6 YAML + §7.2 MDE table (refusal_correct ≈ 0.12–0.13, ≈ 1.2δ; false_refusal stays 0.03, ≈ 3–4δ),
ADR-0007, interfaces `MetricPolicy` default comment, T1.2 S6, T6.3 context, decisions D28 marked.

## 3. Tier-1 judge cap = `budget.max_requests_per_run` only (D143)

`RunnerConfig.judge_max_calls` removed (T1.2, T1.8, T1.12). Mechanism: new read-only
`Budget.requests_remaining` (interfaces §3, T1.4); the runner checks it before each judge call →
`judge_cap`, run stays complete. Nightly tier-1 uses `examples/live/pruefstand.nightly.yaml` (60, splits
`smoke_live`+`smoke`; added by T1.12; T1.11, T5.2b, ci-cd.md updated). test-matrix row added.

## 4. T4.7a CPU-slice reviewer (D144)

SPEC §3 step 4 documents the local non-qwen GGUF reviewer (compose `llm`), never an external provider.

## 5. Ops choices (D145)

- T6.2a: `$PRUEFSTAND_HOME` default `~/pruefstand`; processed state on branch `executor-state`; single
  runbook `docs/ops/runbook.md` (pointer file `gate-executor-runbook.md` dropped).
- T6.2b: `maintenance.yml` replaced by `backup.yml` (`0 6 * * 0`) + monthly `baseline-prune` job in
  `nightly.yml`; `scenarios-statistical` renamed `cause-switches` (tier-2 nightly, T6.3 script) + `contamination-probe`.
- T6.3: job name `cause-switches`. T6.5: runbook path. T0.3: `$PRUEFSTAND_HOME` ownership note (+ typo fix).
- T0.5: `release` environment no reviewer (already "require branches up to date" off; nightly status posted).
- T8.5/T9.2/ci-cd: deploy runbook folded into `docs/ops/runbook.md` §9; T8.5 uses `baseline publish-dashboard`
  with `DASHBOARD_DATA_PAT`. T9.1a already compliant (no docs-deploy, no reviewer).
- docs/ops/runbook.md: §0 first-time install and §9 demo deploy added; header points to itself only.

## 6. interfaces.md additions

§7 `prune_baselines`, `push_dashboard_data`, baseline layout `<fp>/<ref>/` + `history/<run_id>/` + `index.json`
(T6.1 layout corrected to match ADR-0004/data-model); §15 CLI `baseline prune`, `baseline publish-dashboard`;
§10 `labels_document() -> dict` (R1); §10.1 `DashboardSlices.mean_diff` (R2),
`DashboardCase.retrieved_chunk_tenant_ids` (R3), failing-first shard order + `labels.json` (R4); §16 Try-it
HTTP status table + `DEMO_*`, `TRUSTED_PROXY_HOPS`, `NEXT_PUBLIC_DEMO_*` env vars. T8.1 and ui-spec §16 no
longer treat R1–R4 as pending interface changes.

## 7. TASKS dependencies

T8.1 += T1.9; T8.3 += T6.5; T6.3 and T7.2 lose the stale T1.12 (tier 1 no longer hosts statistical scenarios),
T7.2 += T6.3, T6.2b; T9.2 += optional T8.5/T8.3. Prompt cells for T0.2, T4.2, T8.2b reworded so no
non-dependency task ID appears. Script check (IDs in prompt "Depends on" vs TASKS "Depends"): 0 mismatches.

## 8. Stale-name sweep

`ok|fallback|skipped`: none. `judge_mode.*cpu`, `CPU judge`: only negations / negative tests remain
(REVIEW.md round-4 history annotated). `judge_max_calls`, `DASHBOARD_DATA_TOKEN`, `deploy-runbook`,
`maintenance.yml`: none (except D143's statement that the field does not exist). `gate-executor-runbook`:
only T6.2a's "no such file" note. `ephemeral`: only "not ephemeral" / hosted-runner / superseded D5 / ADR
rationale. `gpu-cluster` group: only "never"/superseded/alternatives-rejected rows. `llama` as nightly
judge: none. `answer hash`: only the "this wording is wrong" rule statements and T5.1's grep check.

## Open points for the owner

- Gemma 27B-class nightly judge int4 checkpoint and Gemma terms (DATA_LICENSES §5) are **verify** items for T3.1b.
- `Budget.requests_remaining` is a new interface member (pre-approved here for T1.4/T1.8).
