# 0013 — Observability: structlog + OpenTelemetry

- Status: Accepted (revised 2026-10-31: round 8 executor health, judge state; round 9 X3.4, X3.9, X3.13; round 11 D224-D226, AI11-01/AI11-10)
- Date: 2026-10-27
- Tasks: T1.1, T1.8, T3.2, T5.1

## Context
Runs are long, run in parallel and call external systems. Debugging a failed gate in CI needs structured
logs that can be correlated. The cost claims need a record of every call.

## Decision
- `pruefstand.core.logging.get_logger` wraps **structlog**. It uses the JSON renderer in CI (`CI=true`) and the console renderer locally.
- Standard fields: `ts, level, event, logger, run_id, case_id, tenant, metric, model, duration_ms, error_type`.
  Never logged: secrets, full prompts at INFO level, other tenants' text.
- **OpenTelemetry** spans wrap `run`, `case`, `target.query`, `llm.call` and `gate.evaluate`. The exporter is off by default
  and sends OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- LLM calls are also recorded in `llm_calls.parquet` (interfaces §3).
- rag-demo follows the same logging conventions with its own copy of the code, propagates the request id, and serves `/v1/health`.
  Runtime counters (`<think>` strip counts, `truncated_chunks`, request counts) are in `/v1/health`; `/v1/info.serving`
  holds only static fields (engine, engine version, quantization, GPU model, model file SHA-256, `cpu_model` on CPU),
  because it enters `target_fingerprint`.
- Judge health is recorded per run in `run.json`: `judge_mode` (`github | local | skipped`), `judge_drift`
  (50 anchors, `judges/drift.py` `anchor_agreement`: drift iff ≥ `max(3, ceil(0.1 · n))` anchor verdicts
  changed, hosted and local alike, round 12 N3; SPEC §5.4), `judge_fallback` (judged metrics
  informational, D224),
  `judge_degraded` (> 5 % judge errors), per-metric judge error counts and the `judge_truncated` count
  (truncated case ids are listed in the report); the PR comment and dashboard show them.
- **Serving health** (AI11-01): `counts["model_reloads"]` (native responses with `load_duration` > 1 s
  after preflight) is recorded per run; > 0 aborts the run. An infrastructure failure records
  `stop_reason="aborted"` and `RunManifest.infra_error` (`str | None`, `"<kind>: <detail>"`, D245), posts commit status `error` and is
  retried once after `health.sh --repair` (D226).
- **Executor ops.** The private executor writes `heartbeat.json` (timestamp, last job) to the public
  `dheena18/pruefstand-dashboard-data` repo at every job end **and every 15 min during long jobs**
  (D225), so a healthy nightly never looks down; the public hourly `executor-health.yml` opens or
  updates an issue when it is older than 2 h (`ci-cd.md`, `docs/ops/runbook.md`). Round 13 (D311, A13-M3/M4):
  `last_nightly_status` has one value set, `ok | failed | aborted: window_exceeded | skipped: maintenance |
  skipped: runner busy | skipped: preflight <reason>`; a skip never updates `last_nightly_at`, so the 26-h
  watchdog still fires for a series of skips; a `maintenance` flag (file present) suppresses the health-field
  alerts during planned work while a stale timestamp still alerts; `drift_no_release_baseline` and
  `runner_version` are reported too.

## Alternatives considered
| Option | Why not |
| --- | --- |
| stdlib logging only | Unstructured, no context binding |
| Langfuse/LangSmith | Puts an external SaaS on the core path; can be an option later |

## Consequences
- Positive: CI logs can be grepped, and the cost claims have evidence behind them.
- Negative: a small overhead. The OTel dependencies are an optional extra (`pruefstand[otel]`).
