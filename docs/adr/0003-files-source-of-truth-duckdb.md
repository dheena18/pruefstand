# 0003 — Run artefacts are files; DuckDB is an index; no Postgres

- Status: Accepted
- Date: 2026-10-27
- Tasks: T1.8, T6.1, T8.1

## Context
Spec v1 proposed DuckDB locally and Postgres for the demo. Two SQL dialects mean the store code and its
tests have to be written twice. The GitHub Action runs in users' CI, where there is no database server.
The dashboard only needs to read results.

## Decision
- The source of truth for each run is `runs/<run_id>/{run.json, results.parquet, responses.jsonl, llm_calls.parquet, gate.json}` (interfaces §1.4).
- `RunIndex` (DuckDB, read-only analytics) can be rebuilt from those files at any time. It is a cache and never the authority.
- The caches (`target`, `llm`) are `diskcache` key-value stores (ADR-0006).
- **Postgres is dropped.** The dashboard reads static JSON exported from the artefacts.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Postgres everywhere | Every CI job would need a database server, plus the ops work to run it |
| DuckDB as primary store | A single-writer file handles concurrent runner writes badly, and its binary format changes between versions |
| SQLite as primary | Same problems; files plus Parquet are simpler to ship as CI artefacts |

## Consequences
- Positive: artefacts can be moved anywhere (CI artefacts, a git branch, object storage later), can be diffed, and the dashboard reads them without a backend.
- Negative: ad-hoc queries across runs need `RunIndex.refresh()` first.
- Rule: a new persisted field goes into the Pydantic model and the JSON Schema. It is never added only to DuckDB.
- Run state that decides how a run is read (e.g. `judge_mode`, `judge_drift`, `judge_degraded`, `judge_fallback`, `complete`, `stop_reason`, `infra_error`, `counts["model_reloads"]`) lives in `run.json`, so every consumer (gate, report, dashboard) sees the same value (revised 2026-10-31, round 8; round 11 D224, D226).
