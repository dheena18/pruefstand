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

Public data only: the GII law texts (pinned, SHA-256 checked) and the committed slice corpus and pilot questions.
Private docs, canaries and held-out data never enter the job; `LLMPolicy` (`datagen_policy`) still refuses them.

## What you do, once and per run

1. **Once, review and merge the PR** that adds this workflow. It is yours to merge: it adds `models: read` to a
   public workflow (guard allowlist `MODELS_READ_FILES`). The Run button only lists workflows that exist on `main`.
2. **Once, check the repository settings.** Settings → Actions → General: Actions must be allowed (they are, other
   workflows run). The workflow sets its own `permissions:`, so the default-token setting does not matter and no
   secret is added. GitHub Models needs no switch for a personal repository; if the first run answers HTTP 403 on
   `models.github.ai`, check [Models access for the repository](https://docs.github.com/en/github-models) (an
   organisation would enable Models under Settings → Models).
3. **Dispatch it** (browser: repository → Actions → `cassettes-models` → Run workflow, branch `main`; GitHub
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

- **Budget.** `DAILY_CAP` (120 calls per UTC day over all runs, free tier: 150 low-tier and 50 high-tier requests
  per day) and `budget_calls` (per run) both apply; a stage that does not fit the rest of the day is skipped with a
  warning, never started. The `Llama-3.3-70B` calls are high-tier: keep a `check` or `t45_perturb` day apart from
  a long `generate` day if the 50 per day are reached.
- **Pace.** `PAUSE_S=4.5` s between two `indomain_dev` calls (13 per minute, limit 15). The two pytest stages do
  not pace themselves; a 429 fails the stage, rerun after a minute.
- **Cache.** `actions/cache` keeps (a) the daily ledger, key `gh-models-ledger-<UTC day>-<run>`, restored by day
  prefix so a new day starts at zero; (b) the in-domain answers, key `gh-models-indomain-<hash of the two prompts>-<run>`,
  restored by prefix, so each run extends the previous one and a changed prompt starts a new cache; (c) the T4.2
  and T4.5 cassettes under an exact key (hash of pins, prompts and recording tests, plus the model ids for T4.5):
  the same inputs hit the cache and make **no** call. Entries are evicted after **7 days without access**, and
  the repository cap is **10 GB** (oldest first); every restore renews an entry, so a daily or weekly run keeps it
  alive. After a longer pause the cache is empty and the answers are generated again (the artefact of an earlier
  run seeds it locally through `data/raw/indomain_dev_cache`, not in Actions). A cache entry made on a branch
  other than `main` is not visible to `main`: always dispatch on `main`.

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
