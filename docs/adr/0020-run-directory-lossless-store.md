# 0020 — Run directory: lossless `scored.jsonl`, atomic writes, exact judge-request accounting

- Status: Accepted
- Date: 2026-11-01
- Tasks: T1.8 (also read by T6.1, T8.1)
- Amends: `docs/architecture/interfaces.md` §1.4 (run artefacts), §3 (`Budget`), §7 (`ArtifactStore`)

## Context
T1.8 requires `read_run(write_run(run)).results == run.results`. `results.parquet` has exactly the 13
columns of interfaces §8 (one row per case and metric), so it holds neither the `TestCase` body
(question, reference, gold documents, ...) nor the `MetricValue.details` of a metric; `responses.jsonl`
holds only `CaseRecord`s. `ScoredCase` cannot be rebuilt from those files. Separately, the runner must
release `2 - used` reserved requests per judge call (R9 X4.5), but `Budget` is shared by concurrent calls
and exposes no per-call usage.

## Decision
1. A run directory gains **`scored.jsonl`**: one `ScoredCase` (case + all metric values with details)
   per line, in case order. It is the lossless source of `RunResults.values`; `results.parquet` stays the
   13-column analytics view and `responses.jsonl` stays one `CaseRecord` per line. `write_run` records
   the SHA-256 of `results.parquet`, `responses.jsonl` and `scored.jsonl` in `run.json`
   (`RunManifest.artifact_sha256`, written last). `read_run` checks, in this order: regular non-symlink
   file, size cap, streamed hash (`StoreIntegrityError` on a mismatch or a missing entry), and only then
   parses the jsonl files. It never opens `results.parquet` with a parser: the parquet footer of an
   untrusted file is itself a bomb (a 222-byte file makes polars abort the process), and the file is a
   derived view. Consumers of the parquet (gate input, `RunIndex`, baselines, dashboard export) must
   verify the hash before parsing, or rebuild the view from `scored.jsonl` with `results_frame()`.
2. Writes are atomic: `write_run` fills a hidden sibling directory and `os.replace`s it into place
   (a stored run is never overwritten); `mark_aborted` and `add_counts` write `run.json.tmp` and
   `os.replace` it. A failure removes the temporary files.
3. `llm.budget` gains `tally_charges()` / `ChargeTally`: a context-variable scope that counts the
   requests, USD and tokens charged by `Budget.charge` inside it (nested scopes all count; concurrent
   tasks stay separate). The runner uses one scope per judge call to release exactly the unused
   reservation and one scope per run for `RunManifest.cost`. `Budget`'s own behaviour is unchanged.
4. `DiskKVCache` uses stdlib `sqlite3` (BLOB values, no pickle) instead of `diskcache`, whose pickle-deserialisation advisory (PYSEC-2026-2447) fails the pip-audit gate; no ignore entry.
5. Run id format: `<UTC yyyymmddTHHMMSS>-<6 hex>` (`store.artifacts.new_run_id`).

## Alternatives considered
- Put the case body into `results.parquet`: breaks the 13-column contract the gate, `RunIndex` and the
  dashboard rely on.
- Wrap each `CaseRecord` line of `responses.jsonl` with the scored case: breaks every reader that parses
  that file as `CaseRecord`, and baselines drop `responses.jsonl` from `history/`.
- Release by a global charge difference: wrong under concurrency (other tasks' charges leak in).

## Consequences
- Positive: exact round trip; gate and report code can load a stored run as `RunArtifacts`.
- Negative / cost: one more file per run (about the size of `responses.jsonl` without the chunks).
- `scored.jsonl` is sensitive like `responses.jsonl` (full `TestCase`: canary tokens in `forbidden_strings`, gold text); same retention, never published unmasked.
- Follow-ups: T6.1, T8.1 and `RunIndex` must verify `artifact_sha256` before parsing the parquet (or rebuild it with `results_frame()`); T1.10 treats a `StoreError` from the `DiskKVCache` constructor as no cache.
- Follow-ups: T6.1 `LocalDirBaselineStore` / `GitBranchBaselineStore` must keep `scored.jsonl` next to
  `results.parquet` (and compress it like `responses.jsonl.zst`) if baselines are to be read back as
  `RunArtifacts`; T8.1 sanitiser must mask `scored.jsonl` like `responses.jsonl`.
