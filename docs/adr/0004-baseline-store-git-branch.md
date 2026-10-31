# 0004 — Baselines as plain files in a protected branch of the private executor repo, keyed by fingerprint

- Status: Accepted (revised 2026-10-28, round-1 and round-2 planning reviews: signatures dropped; revised 2026-10-31, round 8: no ad-hoc baseline (D103), bounded retention (D110), dashboard export repo (D108); revised round 9 (X2.6, X2.7): baseline files outside git, index-only branch, encrypted backup; revised round 10 (D197, D209): baseline files and backups on the NAS dataset, `data_root` default `$PRUEFSTAND_DATA_ROOT/baselines`; round 11 (D211, D229): executor user `pruefstand`, mandatory weekly laptop copy of the backup)
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
- CI store (`GitBranchBaselineStore`, X2.7, D209): the baseline **files** live on the **NAS dataset**
  mounted on the executor VM at `/mnt/pruefstand`, under `BaselineStoreConfig.data_root`, whose default
  is **`$PRUEFSTAND_DATA_ROOT/baselines`** (= `/mnt/pruefstand/baselines`), falling back to
  `$PRUEFSTAND_HOME/baselines` (local disk) when `PRUEFSTAND_DATA_ROOT` is unset (laptops, tests). The
  cluster never reads or writes baselines (it holds only Ollama). Layout: `<eval_fingerprint>/<ref>/{run.json,
  results.parquet, responses.jsonl.zst, manifest.json}` (the current baseline; `responses.jsonl.zst`
  only here, never in history) plus `<eval_fingerprint>/history/<run_id>/{run.json, results.parquet,
  manifest.json}` per promotion (**last 20 kept** per fingerprint). `ref` ∈ {`main`, `nightly-b<k>`, `release-b<k>`} (round 12 N1.4; round 13 D305: the release anchor is block-wise).
  `manifest.json` lists the sha256 of every file; it is checked on every read (integrity, not
  authenticity). NAS rules (`gpu-cluster.md` §9): single writer (`baseline-promote.yml`), each run dir
  written as `<run_id>.partial` and renamed once complete, run dirs immutable afterwards, `index.json`
  updated in git only after the rename; no lock files on the NAS (the GPU lock is on the VM disk). If
  the mount is missing (`mountpoint -q`), promote and gate fail loudly instead of reading a stale or
  empty directory. The files are also in the weekly `age`-encrypted backup bundle (X2.6), stored on the
  NAS under `$PRUEFSTAND_DATA_ROOT/backups/` and copied weekly to the owner's laptop (mandatory, receipt
  file watched by `backup-check`, Y5.5).
- The branch **`baselines`** of the **private** executor repo `dheena18/pruefstand-gate` keeps
  **only** a small `baselines/index.json` (per `(fp, ref)`: ordered run ids + manifest sha256, newest
  = current). The repo therefore no longer grows with every promotion (X2.7).
- **No signatures.** Write access to the VM (executor user `pruefstand`, and the owner user, which is
  root-equivalent there, `security.md` C18), the NAS dataset and the private repo is the trust boundary. Only `baseline-promote.yml` writes baselines (files and index), with the private
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
  per fingerprint under `history/` on the NAS and deletes older ones, and deletes whole
  `<fp>/` trees of fingerprints with no promotion for 90 days (release baselines are kept); it updates
  `index.json` in a normal commit. Older baselines stay available only in the encrypted weekly
  backups (8 kept on the NAS, more on the owner's laptop). No branch rollover is needed; the
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
| Baseline files on the VM's local disk | Not shared with the backup target and limited in size; the NAS is the one durable store, and baselines need no locking (single writer) |
| Ad-hoc main run in the PR job when no baseline exists (round-7 design) | +20 min per job, and one documented variant let a gated PR pass without comparison |

## Consequences
- Positive: the baseline index is versioned, private and auditable through git history; the repo stays
  small; reads stay fast and local to the executor.
- Negative: the baseline files depend on the NAS dataset and its mount on the VM; a dropped mount
  fails promote and gate runs loudly, and losing the dataset means restoring from the newest
  encrypted backup (on the owner's laptop if the NAS copy is lost too) (`docs/ops/runbook.md` §5) or re-promoting from `main`. Dashboard and public users
  see only sanitised baselines. After every `eval_fingerprint` change (dataset release, judge or metric
  version bump, `judge_epoch` bump) gated PRs fail until `baseline-promote` has run once (the runbook
  says how to trigger it). Judge drift alone never changes the fingerprint (X3.3).
- Runs with different fingerprints are never compared: `evaluate_gate` raises `GateInputError`. A sha256
  mismatch on read raises `StoreError` (T6.1).
