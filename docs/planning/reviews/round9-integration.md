# Round 9 integration log — integrator A

Scope: cross-file items left after the six fixers applied `round9-resolution.md`, plus the env/secrets
cleanup (with round-10 Z1/Z3/Z7 facts applied to `.env.example` and `docs/ops/secrets.md`). Integrator B
owns `docs/engineering/gpu-cluster.md`, `prompts/T0.6*`, `T3.1a*`, `T3.1b*`, `tasks/PARALLEL-PLAN.md`,
`prompts/_lead-agent.md`; none of these were edited here.

## 1. Cross-file items

| Item | Result | Files |
| --- | --- | --- |
| CLAUDE.md §6 tier-1 scope (X5.6) | already correct (hard fails + `error_rate` only); no change | – |
| `configs/demo.yaml` → `apps/rag-demo/configs/rag.public.yaml` | replaced; T8.5 "Docs to update" now says "check still names" | ci-cd.md (deploy row), docker.md (`demo` profile, `rag-demo` row), security.md D2, ADR-0012, T8.5 |
| Raw-data allowlist `tests/**/fixtures/**` (X1.3) | already in CLAUDE.md §9, D148, T2.1, testing-strategy, test-matrix; no change | – |
| data-model §6/§7 baseline layout + full-bundle backup (X2.6/X2.7) | already correct; D63 marked "refined by D157"; test-matrix backup row path fixed (`infra/gate-executor/host/backup.sh`, `*.bundle.tar.age`) | decisions.md, test-matrix.md |
| SPEC §5.4 `judge_epoch` = one integer | "per judge" removed in prose and fingerprint block (interfaces §1.4 wins) | SPEC.md |
| `gate-router.yml` owned by T6.2b | TASKS T6.2b row and prompts already said so; ci-cd §1.1 row now says "owned by T6.2b" | ci-cd.md |
| Executor concurrency `inputs.pr \|\| inputs.sha \|\| 'poll'` | final form in T6.2b Context + `test_check_workflows.py` rule and ci-cd §6; T7.2 now only adds the `sha` input (no guard change) | T6.2b, ci-cd.md, T7.2 |
| Absolute WARN rule + `ndcg_at_k` gated | interfaces §9 `decide_absolute` comment fixed (was "k/n > max_value") to Wilson lower > `max_value/2`, plus paired-WARN raise in `evaluate_gate`; T1.2 states the rule and that the shipped policy gates `ndcg_at_k`; T1.6/T1.7/SPEC §7.2 already matched | interfaces.md, T1.2 |
| Informational reasons `tier1_deterministic_only`, `tier1_injection_reported`, `judge_truncated`; no `context_truncated` | `judge_truncated` added to the interfaces §9 code list and `evaluate_gate` mapping comment (rule: > 5 % of a judged metric's applicable cases truncated); truncated values are computed on the truncated input (interfaces §5 wins over SPEC's old `not_applicable`); T5.2b informational switches + `test_informational.py` cases (7.5 % → reason, 5 % → none); T1.10 S4b order; SPEC §7.3/§7.6, ADR-0009, ADR-0013 reworded. `grep context_truncated` outside reviews → 0 | interfaces.md, SPEC.md, ADR-0009, ADR-0013, T5.2b, T1.10 |
| M02 expectation in SPEC RQ3 | M2 row now matches T7.1a (256-token sub-chunks; `answer_correctness`/`faithfulness` gated, `evidence_recall` secondary, `multi_hop` informational) | SPEC.md |
| Test-matrix open rows | re-derived: T1.9 lacked tests for `write_gate_json`, `labels_document`, parametrised `set_check` and judge-truncated ids → added (`test_json_report.py`, `test_labels.py`, `test_github.py`, `test_markdown.py`); T1.9 `set_check` signature gains `no_baseline` and the "warn: …" description fixed to the interfaces §10 table; rag-demo API (T3.2/T3.6), GPU scripts (T3.1a), pre-deploy probes (T8.5) already had their tests → covered; weak `evidence_recall` (T7.3 `test_evidence_recall.py`) and `check_numbers_in_prose` (T9.3 row renamed `test_check_numbers_in_prose.py`) → covered. Totals: 239 covered, 1 weak (backup drill), 0 open | T1.9, T9.3, test-matrix.md |

## 2. Env / secrets

- Stale names: `PRUEFSTAND_GPU_LOCK_HELD`, `DASHBOARD_DATA_TOKEN`, `PYPI_TOKEN` were already gone outside
  reviews (`PYPI_TOKEN` remains only as a *negative* assertion in T9.1a's guard test). `FLY_API_TOKEN` is now
  "only if the owner picks Fly.io" (T8.5, T0.5 S13, secrets.md).
- `PRUEFSTAND_MODEL_CACHE` dropped (round 10): compose `llm` mount uses `LIVE_MODEL_DIR`
  (default `${HOME}/.cache/pruefstand/models`) in docker.md and T0.3. testing-strategy §3.9 endpoints →
  `OLLAMA_GPU0_URL`/`OLLAMA_GPU1_URL`.
- New `.env.example` (sections LOCAL = VM via VS Code Remote-SSH, WSL optional; VM = executor; CLUSTER = Ollama
  only, incl. `OLLAMA_MODELS=$CLUSTER_DATA_ROOT/truenas-ollama/ollama-models`). `OLLAMA_BASE_URL` from the original
  brief is replaced by `OLLAMA_GPU0_URL`/`OLLAMA_GPU1_URL` (round 10 Z1).
- New `docs/ops/secrets.md`: one table for secrets, one for variables; SSH key created on the VM in T0.7,
  never in GitHub; no password stored anywhere; App keys/PATs only as repo/environment secrets.
- Pointers to secrets.md: CLAUDE.md §5 and §8, T0.0, T0.3 S3, T0.5 Context/S13/interfaces block, T1.4, T2.6,
  T4.7b, T5.2a, T8.4 S5, T8.5, T9.1b, docker.md, security.md, ci-cd.md Secrets row, runbook §7 (age recipient →
  `AGE_RECIPIENT` in the VM `.env`).

## 3. Final checks

- Prompt "Depends on" vs TASKS (script: every `T*` id in the prompt header equals the TASKS row's Depends
  ids, 75 tasks): 1 mismatch found and fixed (TASKS T7.3 gains T4.2, which the prompt needs for
  `evidence_span`). Now 0.
- Stale-name grep (outside reviews and B's files): clean.

## Left for others

- **Integrator B / round-10 pass:** `gpu-cluster.md` and `prompts/T3.1a*` still use `PRUEFSTAND_MODEL_CACHE`,
  `PRUEFSTAND_VLLM_*_URL`, `VLLM_API_KEY`, `GPU_HOST` and vLLM/TEI; T3.1a's `.env.example` line must append to the
  CLUSTER/VM sections and name only variables in secrets.md. The test-matrix GPU-scripts row will move to
  `infra/cluster/`.
- **Round-10 follow-up:** TASKS has no T0.7 row yet (Z6); docker.md `gpu` profile (vLLM/TEI services,
  `VLLM_GENERATOR_API_KEY`), T6.2a `PRUEFSTAND_CANDIDATE_API_KEY` (meaning under Ollama), deployment.md
  `RAG_LLM_BASE_URL`, CLAUDE.md §2/§3 map (VM as primary dev machine) are not rewritten here.
