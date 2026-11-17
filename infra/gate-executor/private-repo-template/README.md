# pruefstand-gate (private gate executor)

Private repository of the Prüfstand **gate executor** (`CLAUDE.md` §2 of the public repo
`dheena18/pruefstand`, ADR-0005). It holds the trusted workflows that run on the persistent self-hosted
runner on the VM (label `a40`), the executor code, the `baselines` branch (only `baselines/index.json`) and
the `executor-state` branch (`state/processed.jsonl`, `state/nightly_counter`).

**Do not edit synced files here.** `infra/gate-executor/{orchestrator,llm-proxy,host}`, `.github/workflows/*.yml`,
this `README.md`, `.gitignore` and `SYNCED_FROM` are copied from the public repo by its
`scripts/sync_executor.sh` at an annotated maintainer tag `executor-<YYYYMMDD>[.N]` on `main`; change them there,
tag, and sync again (the script opens a PR here). `SYNCED_FROM` names the tag and commit.

No secrets in files: the `pruefstand-bot` App key, the dashboard-data PAT and the other credentials are
repository or environment secrets of this repo; the runner's own values live in `runner.env` on the VM
(`docs/ops/secrets.md` of the public repo), never here.

## First fill of the empty repo (owner, laptop, once)

In a shell with git and the owner's GitHub login (Git Bash or WSL on Windows), after the public `main` contains
the executor code to start with; replace `YYYYMMDD` with today's date:

    git clone https://github.com/dheena18/pruefstand.git pruefstand-sync && cd pruefstand-sync && git tag -a executor-YYYYMMDD -m "first executor sync" origin/main && git push origin executor-YYYYMMDD && bash scripts/sync_executor.sh executor-YYYYMMDD --init

`--init` refuses a private repo that already has a branch. Later syncs use the same script without `--init`
(it opens a PR in this repo); `--dry-run` shows the diff and pushes nothing.
