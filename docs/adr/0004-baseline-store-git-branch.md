# 0004 — Baselines as plain files in a protected branch of the private executor repo, keyed by fingerprint

- Status: Accepted (revised 2026-10-28, round-1 and round-2 planning reviews: signatures dropped; revised 2026-10-31, round 8: no ad-hoc baseline (D103), bounded retention (D110), dashboard export repo (D108); revised round 9 (X2.6, X2.7): baseline files outside git, index-only branch, encrypted backup; revised round 10 (D197, D209): baseline files and backups on the NAS dataset, `data_root` default `$PRUEFSTAND_DATA_ROOT/baselines`; round 11 (D211, D229): executor user `pruefstand`, mandatory weekly laptop copy of the backup)
- Amended by: [ADR-0019](0019-local-model-storage-small-disk.md) (2026-10-31: the data root is a plain directory on the VM disk, no NAS mount; backups = TrueNAS zvol snapshots + laptop copy)
- Date: 2026-10-27
- Tasks: T6.1, T6.2a, T6.2b

## Context
Each PR run is compared against a baseline. GitHub Actions artefacts expire after at most 90 days and
are awkward to look up from other workflows. A baseline is only comparable when the dataset, judge,
prompt, metric, corpus and serving versions all match (interfaces §17). Baselines contain answers and
retrieved chunk text, including private-tenant documents and canaries, so they must not be public.
Round 2 found that signing baselines inside a single trust domain (the private repo signs and verifies
its own files) adds no security, only setup. Round 8 found that (a) an ad-hoc baseline path was
defined three different ways and one of them let a gated PR pass with no comparison, and (b) a
protected, no-force-push git branch cannot shrink, so "prune" needs an honest definition. Round 9
found that committing `results.parquet` / `responses.jsonl.zst` on every promotion reaches GitHub's
1 GB guidance within months, and that renaming the branch to an archive keeps every object reachable,
so the repo never shrinks (R9-11).

## Decision
- A `BaselineStore` protocol with two implementations: `LocalDirBaselineStore` (dev, tests) and
  `GitBranchBaselineStore` (CI). No other store type exists until a task adds one.
- CI store (`GitBranchBaselineStore`, X2.7, D209): the baseline **files** live in the **data root**
  on the executor VM, `/mnt/pruefstand`, a plain directory on the VM's disk (a 500 GB zvol on TrueNAS; ADR-0019), under `BaselineStoreConfig.data_root`, whose default
  is **`$PRUEFSTAND_DATA_ROOT/baselines`** (= `/mnt/pruefstand/baselines`), falling back to
  `$PRUEFSTAND_HOME/baselines` (local disk) when `PRUEFSTAND_DATA_ROOT` is unset (laptops, tests). The
  cluster never reads or writes baselines (it holds only Ollama). Layout: `<eval_fingerprint>/<ref>/{run.json,
  results.parquet, responses.jsonl.zst, scored.jsonl.zst, manifest.json}` (the current baseline; the two
  `.zst` files only here, never in history; `scored.jsonl.zst` is the lossless source of `RunResults.values`, T6.1 D441) plus `<eval_fingerprint>/history/<run_id>/{run.json, results.parquet,
  manifest.json}` per promotion (**last 20 kept** per fingerprint). `ref` ∈ {`main`, `nightly-b<k>`, `release-b<k>`} (round 12 N1.4; round 13 D305: the release anchor is block-wise).
  `manifest.json` lists the sha256 of every file; it is checked on every read (integrity, not
  authenticity). Data root rules (`gpu-cluster.md` §9): single writer (`baseline-promote.yml`), each run dir
  written as `<run_id>.partial` and renamed once complete, run dirs immutable afterwards, `index.json`
  updated in git only after the rename; no lock files in the data root (the GPU lock is in `/var/lib/pruefstand`). If
  the data root is unusable (missing, not writable, < 20 GB free; `infra_error="data_root_unavailable"`), promote
  and gate fail loudly instead of reading a stale or empty directory. The files are also in the weekly `age`-encrypted backup bundle (X2.6), stored in the
  data root under `$PRUEFSTAND_DATA_ROOT/backups/` (covered by the TrueNAS periodic snapshots of the VM zvol) and copied weekly to the owner's laptop (mandatory, receipt
  file watched by `backup-check`, Y5.5).
- The branch **`baselines`** of the **private** executor repo `dheena18/pruefstand-gate` keeps
  **only** a small `baselines/index.json` (per `(fp, ref)`: ordered run ids + manifest sha256, newest
  = current). The repo therefore no longer grows with every promotion (X2.7).
- **No signatures.** Write access to the VM (executor user `pruefstand`, and the owner user, which is
  root-equivalent there, `security.md` C18), the data root and the private repo is the trust boundary. Only `baseline-promote.yml` writes baselines (files and index), with the private
  repo's own `GITHUB_TOKEN` for the index; the branch is protected (no force-push, no deletion).
- Reads fetch `index.json` (shallow, single-branch clone) and verify the files on disk against the
  manifest sha256 (mismatch or missing file → `StoreError`, T6.1 integration test).
- Lookup is `get(eval_fingerprint, ref)`. **No ad-hoc baseline** (D103): for a gated PR with no
  baseline for its fingerprint, the executor posts `pruefstand/gate` = `failure` "no baseline for <fp>;
  run baseline-promote" and never `success`. For `main` and nightly runs a missing baseline gives
  `INSUFFICIENT_DATA` and exit 0.
- `baseline-promote.yml` promotes main's run on every new `main` head and the newest complete nightly
  run (nightly fingerprint) as `nightly-b<k>`; the **release run of all of `full`** (the newest `v*` tag's image,
  run alone on a night while `release-b0..b2` of that tag are missing for the current fingerprint) is promoted
  as `release-b0`, `release-b1`, `release-b2` (one block-*k* projection each), so a fingerprint change rebuilds
  the anchor instead of leaving drift empty until the next tag (AI13-09, A13-M5, D321).
  Runs flagged `judge_fallback`, `judge_drift`, `judge_degraded`, with a judged metric informational for
  `judge_truncated`, or with `infra_error` are never promoted (AI13-08, D321).
- Incomplete runs (`complete = false`) are never promoted.
- A sanitised copy (run.json, gate.json, results without text, `runs/index.json`) is pushed to the
  separate public repo `dheena18/pruefstand-dashboard-data` with a sha256 manifest (D108).
- **Retention (D110, X2.7):** the monthly `baseline-prune` step (run by `baseline-promote.yml` on its
  first poll after 00:00 UTC on day 1, so baselines have exactly one writer) keeps the last 20 entries
  per fingerprint under `history/` in the data root and deletes older ones, and deletes whole
  `<fp>/` trees of fingerprints with no promotion for 90 days (release baselines are kept); it updates
  `index.json` in a normal commit. Older baselines stay available only in the encrypted weekly
  backups (8 kept in the data root, more on the owner's laptop). No branch rollover is needed; the
  nightly `repo-size` step stays as a guard and fails above 1 GB.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Orphan branch in the public repo | Public chunk text and canaries; writable by any `contents: write` workflow |
| cosign `sign-blob` on each manifest (round-1 design) | Same trust domain signs and verifies; adds setup, no protection |
| Actions artefacts | Expire; cross-workflow lookup needs API calls and a token; small storage quota on private repos |
| Actions cache | Entries can be evicted |
| Object storage | Extra infrastructure and credentials; not needed at this scale |
| All baseline files in the git branch (round-1 to round-8 design) | The private repo grows by every promotion and cannot shrink without force-push or deleting archive branches (R9-11) |
| Baseline files on the cluster disk (round-9 design) | The cluster's local disk is 93–98 % full and holds no state of ours (round 10); the executor moved to the VM |
| Baseline files on a NAS share (round-10 design) | The VM cannot reach its TrueNAS host over NFS without a bridge; the VM's own 500 GB zvol is large enough and is snapshotted by TrueNAS (ADR-0019) |
| Ad-hoc main run in the PR job when no baseline exists (round-7 design) | +20 min per job, and one documented variant let a gated PR pass without comparison |

### T6.1 implementation notes (D441-D445)
- Reads hash and parse the same in-memory bytes: `manifest.json` (pinned by `index.json` for the git store) pins the stored files, `run.json`
  pins the uncompressed data files, zstd frames are inflated with a hard cap, `results.parquet` is hashed and never parsed; fingerprints,
  refs and run ids are checked against a strict charset and symlinks are refused at every level.
- Promotion stages `<ref>.<hex>.partial`, swaps it in keeping `<ref>.<hex>.old`, renames `history/<run_id>`, pushes the index (3 attempts)
  and then forgets the `.old` copy; any failure rolls the data root back. A `.old` directory without its ref is an error, never "no baseline".
- Retention (`prune_baselines`, D445): the newest 20 `history/` entries per fingerprint plus the history entry of every current baseline;
  fingerprints unused for 90 days lose everything except `release-b<k>`; the index is reconciled with the disk in one commit.
- `index.json` is read with `git clone --depth 1 --filter=blob:none --single-branch` (the branch holds one small file).

## Consequences
- Positive: the baseline index is versioned, private and auditable through git history; the repo stays
  small; reads stay fast and local to the executor.
- Negative: the baseline files depend on the VM disk; an unusable data root fails promote and gate runs
  loudly, and losing it means rolling back a TrueNAS snapshot or restoring from the newest encrypted backup
  (on the owner's laptop) (`docs/ops/runbook.md` §5) or re-promoting from `main`. Dashboard and public users
  see only sanitised baselines. After every `eval_fingerprint` change (dataset release, judge or metric
  version bump, `judge_epoch` bump) gated PRs fail until `baseline-promote` has run once (the runbook
  says how to trigger it). Judge drift alone never changes the fingerprint (X3.3).
- Runs with different fingerprints are never compared: `evaluate_gate` raises `GateInputError`. A sha256
  mismatch on read raises `StoreError` (T6.1).
