# GitHub Models recordings in Actions (`cassettes-models.yml`)

`models.github.ai` answers a bare `200 OK` from the VM and from the cloud sandbox (D604), so every real GitHub
Models call of the data tasks runs in GitHub Actions with `permissions: models: read` and the job's own token
(`PRUEFSTAND_GH_MODELS_TOKEN: ${{ github.token }}`, D333). The workflow never commits: its result is an
artefact, and you or the lead turn it into a PR (D900).

| Target (`workflow_dispatch` input) | What it records | Calls |
| --- | --- | --- |
| `indomain_dev` | `indomain_dev.jsonl` (T3.1b S4): questions for the 240 planned public law passages with `openai/gpt-4.1-mini`, second-family spot-check of the first 30 with `meta/Llama-3.3-70B-Instruct`, `assemble` (marks the items `dev_only`, writes the source passage ids that T4.x excludes) | up to 240 + 30 over several days |
| `t42_dataset` | T4.2 datagen and support-check cassettes (`scripts/models/record_cassettes.sh --dataset`, real chunks of the committed slice corpus) | at most 18 |
| `t45_perturb` | T4.5 rewrite and equivalence-check cassettes (`record_cassettes.sh --perturb`, the 8 shared_public pilot questions) | at most 70 |
| `all` | the three in this order, sharing the day's budget | |

Public data only, by construction: the GII law texts (pinned, SHA-256 checked), the committed slice corpus and the
pilot questions are the only inputs. Private docs, canaries and held-out data are not inputs of any step. Do not read
this as "LLMPolicy guards the job": `indomain_cli` calls httpx directly without `LLMPolicy`; the T4.2 stage runs
under `datagen_policy(None)` and the T4.5 stage under the default policy with an empty canary registry.

## What you do, once and per run

1. **Once, review and merge the PR** that adds this workflow. It is yours to merge: it adds `models: read` to a
   public workflow (guard allowlist `MODELS_READ_FILES`). The Run button only lists workflows that exist on `main`.
2. **Once, check the repository settings.** Settings → Actions → General: Actions must be allowed (they are, other
   workflows run). The workflow sets its own `permissions:`, so the default-token setting does not matter and no
   secret is added. ASSUMPTION, not verified: GitHub Models needs no switch for a personal repository; if the first run answers HTTP 403 on
   `models.github.ai`, check [Models access for the repository](https://docs.github.com/en/github-models) (an
   organisation would enable Models under Settings → Models).
3. **Dispatch it on `main`** (the job has `if: github.ref == 'refs/heads/main'`: a dispatch from another branch
   does nothing, because branch caches and ledgers are separate and would bypass the daily cap; browser: repository → Actions → `cassettes-models` → Run workflow, branch `main`; GitHub
   mobile app: repository → Actions → the workflow → Run workflow). Choose `target` and `budget_calls` (default 100).
   Start with `indomain_dev`; run it once per day until the summary says `assembled=true` (about three runs).
4. **Read the job summary** of the run: new calls, cache hits, hit ratio, calls of the day against the cap. A
   quota stop (HTTP 429) is a normal end: the answers so far are cached, dispatch again after the UTC midnight.
5. **Download the artefact** `cassettes-models-<run id>` (run page → Artifacts, kept 14 days). Unzip it, then on
   the VM or the laptop, from a fresh branch of `main`:

   ```bash
   git switch -c data/cassettes-models-$(date +%F)
   bash scripts/models/apply_models_artifact.sh /path/to/unzipped/artefact   # checks SHA256SUMS.txt, copies to the repo root
   uv run pytest experiments/model_selection/tests packages/pruefstand/tests/unit/dataset packages/pruefstand/tests/unit/perturb -q
   git add packages/pruefstand/tests/cassettes experiments/model_selection && git status
   ```

   Commit, push and open the PR as for any task (`gh pr create`). `gh run download <run id> -n cassettes-models-<run id>`
   fetches the artefact where the token has Actions read access.
6. **Then** set the rows of T3.1b/T4.2/T4.5 in `docs/decisions.md` to the real result (the dev-set card and the
   `planned` status of `indomain_dev_sources.json` come from `assemble`) and let the lead update the task status.

## Budget, rate limits and the cache

- **The free-tier numbers are assumptions, not verified**: low-tier models (`gpt-4.1-mini`) 15 requests per minute
  and 150 per day, high-tier models (`Llama-3.3-70B`) about 10 per minute and 50 per day. Measure them with the
  T0.6 quota probe before relying on them.
- **Budget.** `budget_calls` (1 or more; 0 is refused) is the budget of the whole run over all stages: each stage
  deducts what the earlier stages of the run used. `DAILY_CAP` (120 per UTC day over all runs) applies on top.
  A stage that does not fit the rest is skipped with a warning, never started. The quota day is the date the
  run started, also if it crosses UTC midnight.
- **The ledger is a soft counter, not a hard limit.** It lives in `actions/cache`; an evicted entry or a failed
  restore resets the day to zero (the job summary says "Ledger: none restored" in that case and a first run of the day
  looks the same). A ledger file that exists but is corrupt fails closed: the run stops before any call.
  GitHub's own 429 is the real limit.
- **Pace.** `PAUSE_LOW_S=4.5` s between `indomain_dev` generation calls (13 per minute); `PAUSE_HIGH_S=6.5` s for the
  `check` step (`Llama-3.3-70B`, 9 per minute). The two pytest stages do not pace themselves; a 429 fails the stage,
  rerun after a minute. `all` can need about 62 high-tier calls (30 checks + up to 32 T4.5 judge calls) against an
  assumed 50 per day: the summary warns; if a stage stops on 429, dispatch the remaining target the next UTC day.
- **Cache.** `actions/cache` keeps (a) the daily ledger, key `gh-models-ledger-<UTC day>-<run>`, restored by day
  prefix so a new day starts at zero; (b) the in-domain answers, key `gh-models-indomain-<hash of the two prompts>-<run>`,
  restored by prefix, so each run extends the previous one and a changed prompt starts a new cache; (c) the T4.2
  and T4.5 cassettes under an exact key (hash of pins, prompts and recording tests, plus the model ids for T4.5):
  the same inputs hit the cache and make **no** call. Entries are evicted after **7 days without access**, and
  the repository cap is **10 GB** (oldest first); every restore renews an entry, so a daily or weekly run keeps it
  alive. After a longer pause the cache is empty and the answers are generated again (the artefact of an earlier
  run seeds it locally through `data/raw/indomain_dev_cache`, not in Actions).

## The artefact is untrusted input

`apply_models_artifact.sh` refuses any symlink or other non-regular file, any file missing from or not listed in
`SHA256SUMS.txt`, any checksum mismatch, any path outside the result locations (or with `..`), files over 8 MiB and
a total over 64 MiB. Only then it installs the listed files one by one with mode 0644 (no tar, no exec bits). Look at
`git status` before you commit anyway.

## Deviation to know (T4.5)

The recording scenario of T4.5 names an A40 judge for the equivalence check. There is no A40 in Actions, so
`perturb_judge_model` defaults to the GitHub Models cross-check model (family `llama`, not the rewrite family
`gpt`); `meta.json` of the cassettes carries the id, so replay needs nothing else. If the lead wants the
validation answers of the A40 judge, run `pruefstand-lock bash scripts/models/record_cassettes.sh --perturb` on the
VM against the artefact's rewrites; that is a lead decision, not part of this workflow.

## Daily schedule

Not enabled. The workflow file holds a commented `schedule:` block (daily, off-minute). To switch it on, remove
the comment markers; a scheduled run uses the defaults (`indomain_dev`, 100 calls). Scheduled workflows are
disabled by GitHub after 60 days without repository activity.

## Law texts come from a release mirror (D927)

The official site refuses GitHub-hosted runners, so the `indomain_dev` stage downloads the pinned statute archives from the assets of the pre-release `data-pins-2026-11b` (`PRUEFSTAND_GII_MIRROR`). The SHA-256 check against `data/sources.yaml` is the same. When a pin is refreshed (`gii:uwg` is pending), publish the new archive as an asset of the same or a new `data-pins-*` release and update the URL in the workflow step.
