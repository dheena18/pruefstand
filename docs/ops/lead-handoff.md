# Lead-agent handoff (updated 2026-11-03)

Read this first if you are a new lead session. It states where the work stopped, what is open, what is needed from the
owner, and the working rules and traps. The authority order is unchanged: `CLAUDE.md`, then `tasks/PARALLEL-PLAN.md` and
`tasks/TASKS.md`, then this file (a snapshot, delete it when stale).

## 1. State of main

Merged (squash) and green through T3.5 (main at `df1d8f860742`): T0.1-T0.4, T0.6, T0.7, T1.1-T1.13, T2.1-T2.5, T3.1a,
T3.2-T3.5, T4.1, T4.4, T6.1, plus the T3.1b phase 1 (resident set; partial, the rest is open) and the fix PRs. The repo is
public; the ruleset on `main` is active (PR required, 0 approvals, linear history). Required checks: `check`, `scan`,
`images-gate`, `docs-gate`.

Open work: T5.1, T6.4, the wrapper load-log PR (T3.1e; its own PR adds the TASKS.md row; owner merge, D584) and the rest of T3.1b (embedding/reranker
benchmark, budget, candidate swaps by the lead, pins). Check live PR state with the API, not this file. Take the next free
decision number when adding a row (rows D580-D586 are the 2026-11-03 owner decisions) and renumber on collision.

## 2. What is needed from the owner

1. **T0.6 probe verdict.** The owner re-runs the probe (`infra/cluster/feasibility/README.md`, steps 1-5) and pastes the
   result. Before committing it as `infra/cluster/feasibility/probe-<date>.out`, check that it says "go" and contains no
   username, home path, cluster host or port (only `<ollama-bin>`, `<home>`, `<cluster-user>` placeholders, 127.0.0.1:11434
   and the public alias `cairo-s101lp`). Then fill `docs/engineering/gpu-cluster.md` section 0.2 C1-C8 and the Decision line.
   **T3.1a, T3.1b and T3.2 stay blocked until the owner sends the verdict.** The lead never gets access to the cluster account.
2. T0.5 leftovers (later, with T6.2a/T6.2b): the `pruefstand-bot` App and the `gate-router` environment.
3. Every sudo step is an owner step (the agent sudoers file is removed). Changes to the VM firewall, tunnel or systemd units,
   all GitHub settings and rulesets, and the private repo are the owner's.

## 3. What is next (order from `tasks/PARALLEL-PLAN.md`)

- Open: T5.1 (starts with the provisional pins, D580), T6.4, T3.1e (the wrapper load-log PR; its own PR adds the TASKS.md row; owner merge), T3.1b rest (D583), T0.5 leftovers (the `pruefstand-bot` App and the `gate-router` environment, still open).
  Then the Wave 9/10 leftovers (T2.6, T5.2a, T4.5, T4.6, T5.2b, T5.3 PR 1, T4.2). Check each task's `Depends` cell in
  `tasks/TASKS.md` is merged before starting it; one task = one worktree = one branch = one PR.
- Follow-up task rows recorded in `tasks/TASKS.md` (not started): T1.7a, T1.7b, T1.8a, T1.9a, T1.13a, T2.3a, T2.4a, T4.4a.

## 4. Standing rules from the owner

- Lead orchestrates, task agents implement (Sonnet), reviews use Opus. At most 3 task agents at once. Stop agents when their
  PR merges. After a push start ONE `gh pr checks <PR> --repo dheena18/pruefstand --watch` in the background (do NOT pipe
  it: a pipe hides its exit code) and act on its exit. No polling, no sleep loops, short reports.
- Merge yourself (squash, `--match-head-commit <full sha>`) when: CI green on the current head, the fresh-session review has
  no open blocker/major, main is merged in, wave order respected. Report each merge in one line. Review cap: at most 2
  re-review rounds; after that a major blocks only if it touches gate correctness, security or data integrity (confidentiality
  of the public repo counts as security); everything else becomes a follow-up task row plus the PR's Follow-ups. Blockers
  always block.
- Still the owner's: VM firewall/tunnel/systemd/sudo changes, GitHub settings and rulesets, the private repo, anything under
  `/var/lib/pruefstand` or `/home/pruefstand`.
- Secrets: run project scripts that need `~/code/pruefstand/.env` only in a subshell; never print, copy or commit values or
  put tokens on a command line. The repo is public: no real IPs, cluster address or port, usernames or `.env` content.
- No "Generated with Claude Code" (or similar) footer in PR text, comments, issues or reviews. Commit trailers are fine.
- No force pushes; take main with `git merge origin/main` or `gh api -X PUT repos/dheena18/pruefstand/pulls/N/update-branch`.
  Push only after `make check` exits 0 (check the exit status; do not chain a push after a failing check).
- **Rule 1, waiting for the owner.** When you need the owner's input (a decision, an owner step, a verdict): first finish any
  other work that is not blocked; then send ONE message with the question or the "Owner actions" list; then stop and end the
  turn. Do not re-check, do not repeat the message, do not run watchers or loops for things only the owner can unblock, and do
  not react to notifications that change nothing. Continue only when the owner replies.
- **Rule 2, errors and loops.** Stop as soon as: the same error, failing test or CI failure comes back after 2 fix attempts;
  a command, tool call or retry keeps repeating with no progress; or you are unsure why something fails. Stop that work
  (task agents too) and kill any watcher or retry for it. Send the owner one short message: what failed (the key error
  lines, secrets redacted), what you tried, your best guess at the cause, and one clear question or 2-3 options. Then end the
  turn and wait. Never retry blindly, never loop, never sleep-poll. Unrelated, unblocked work may continue.

## 5. Traps found

- Use `env -u GITHUB_TOKEN -u GH_TOKEN gh ...` on the VM. `gh pr merge` needs the FULL head sha.
- gitleaks runs with `--verbose --redact` (in `.github/workflows/security.yml`). It scans ALL refs: a fake secret in any
  branch's history fails every PR's `scan`. Read the finding (rule, file, line, commit) from the job log, then add one narrow
  `.gitleaks.toml` allowlist entry (`condition = "AND"`, exact path, exact synthetic literal). Never guess an allowlist.
- `ruff` caches hide import-sort errors locally: run `uv run ruff check --no-cache .` and `ruff format --check --no-cache .`.
  After merging a PR that adds a dependency, run `uv sync --all-packages --all-extras` before `make check`.
- A PR-body edit can trigger a duplicate `ci` run that gets cancelled; the cancelled run's aggregate `check` shows as failed
  in `gh pr checks`. Judge by the latest `ci` run (`gh api repos/.../actions/runs?head_sha=<sha>`).
- A conflicting PR gets no workflow runs ("no checks reported"): merge main first.
- Load-sensitive tests (re-run them ALONE before blaming a PR): `scripts/tests/test_docker_mk_stack_run.py` signal cases
  (they also fail under `nohup`, which ignores SIGHUP: run `make check` from a normal ssh session or under `setsid`),
  `packages/pruefstand/tests/unit/adapters/test_http_untrusted.py` (timing, seen on CI), `test_citation_forms.py::
  test_runs_in_linear_time`, `metrics/test_review2_hardening.py::...budget_is_shared...`, the ingest linear-time tests.
- Do not `pkill -f` a pattern that also matches your own ssh command line.
- Cluster/GPU work only through `pruefstand-lock` and the wrapper `/usr/local/bin/pruefstand-cluster` (group `pruefstand`,
  NOPASSWD for that one command; no other sudo, no direct `sudo -u pruefstand ssh`). Task agents never touch the cluster;
  the lead runs the real operations (section 6). `MAINTENANCE` handling: see section 6 (D451).

## 6. Model remove / swap authority (owner decision, D451)

The owner lets the lead remove and swap Ollama models without asking, under ALL of these conditions:

1. only after the `:latest` / digest fix is merged and deployed (`make gpu-deploy-bin` done by the owner);
2. only models listed in `infra/gpu/models.yaml`. Anything else on the cluster `/data` (files, other models) belongs to the
   owner: never touch it;
3. only through the wrapper (`make gpu-pull`, `make gpu-rm`, i.e. wrapper `pull` / `rm`); never `ollama rm`, never `rm` by hand;
4. only while no gate or nightly is running. Create `/var/lib/pruefstand/MAINTENANCE` yourself for the remove or swap, run
   the operation under `pruefstand-lock`, and ALWAYS remove `MAINTENANCE` afterwards, also when the operation fails
   (use a trap / `finally`); that one file is the only thing under `/var/lib/pruefstand` the lead may write;
5. never remove the model the current mode is using without switching modes first (`make gpu-up` / `gpu-night-up`);
   and **never remove the generator `qwen3.8:27b-q8_0` (`GENERATOR_TAG`), not even to free space**: if freeing space would
   need it, ask the owner;
6. log every remove or swap (tag, digest, free space before and after) in `docs/engineering/gpu-cluster.md` section 8
   ("Model remove / swap log"), with the cluster paths shown as `<models-dir>`.

Exit 17 of `fetch-model.sh` ("not enough disk") is no longer a stop: the lead may free space by removing catalogue models
that the current task does not need (never the generator). Ask the owner only when that is not enough. Task agents never run any of this.

Amendment (owner decision 2026-11-03, D583): candidate swaps for T3.1b are done BY THE LEAD under D451. The same
conditions apply: catalogue models only, only through the wrapper (`make gpu-pull` / `make gpu-rm`), under
`pruefstand-lock`, only while no gate or nightly runs. The lead sets `/var/lib/pruefstand/MAINTENANCE` and ALWAYS removes
it again, also on failure; every swap is logged in `docs/engineering/gpu-cluster.md` section 8 ("Model remove / swap log").
Step S6 of `prompts/T3.1b-model-benchmark.md` is no longer a HUMAN step. The generator `qwen3.8:27b-q8_0`
(`GENERATOR_TAG`) is NEVER removed, not even to free space.

## 7. Full-speed mode (2026-11-03, time-boxed to about 2 hours, D586)

Reserved decision ranges (2026-11-03): the lead assigned disjoint ranges per agent to avoid merge collisions, so gaps between D-numbers are intentional and rows are not renumbered: D520 T5.1, D540 T6.4, D560 wrapper PR, D580 checkpoint (this PR), D600 T3.1b prep, D620 T3.6.

- At most 3 task agents (D660; the 5-agent full-speed window of D586 is over)
- Docs-only and test-only PRs get one review round, then merge on green. Code PRs get at most 2 review rounds.
- Owner steps are collected in one list and sent once at the end; they never block work. A task that needs the owner is parked.

## 8. Shared-VM discipline (D660, 2026-11-03)

- Full checks go through `make check-vm` (`scripts/vm_check.sh`): at most 2 at once. Targeted tests (`uv run pytest <path>`) while
  working; the full check only before pushing. Tell every task agent this in its brief.
- Never take a timing measurement for a budget (rerank latency, tok/s, TTFT, load times) while other checks run; repeat any
  measurement that was taken under load.
- At most 3 task agents at once (the full-speed window of D586 is over).
- Every watcher or waiter you start ends itself when its PR is merged or closed (a `gh pr checks --watch`, or a loop that tests
  the PR state); never leave one running. No agent kills a process it did not start (no `pkill -f` patterns); only the lead does
  that, during a cleanup, by exact PID. (2026-11-03: ten orphaned waiters, the oldest 35 hours, were stopped; one `pkill -f` by a
  reviewer had killed another session's polling loop.)
- No `git stash` in worktrees: the stash list is shared across all worktrees, so a `stash pop` can apply another session's
  entry. Use a WIP commit on your own branch, or `git diff > patch`. Old stash entries (T1.13) stay untouched.
- Pipe gates: every "only on success" step (commit, push, PR create, merge) tests the exit code of the REAL command, never of
  `tail`, `grep` or `tee` at the end of a pipe. Use `set -o pipefail`, `${PIPESTATUS[0]}`, or write the output to a file and tail
  the file afterwards, and branch with `if ! cmd >file 2>&1; then ...; exit 1; fi`. For the full check test the exit code of `make check-vm` itself (it `exec`s `make check`, so the status is make's own); when the check runs in the background, write `EXIT=$?` right after it into the log and gate on that line. Do not gate on `cmd | tail -1 && next`.
  (2026-11-03: `ruff | tail && git add` let two lint-failing commits through to a PR branch; CI caught them.)


## 9. Merging (D1210)

The lead merges with `scripts/merge_reviewed.sh <pr> <sha> "<reviewer verdict>"` and nothing else; the verdict is the third **argument**
(an env prefix such as `REVIEW_VERDICT=... scripts/merge_reviewed.sh ...` does not match the allow rule `Bash(scripts/merge_reviewed.sh:*)`).
Use it only after an approving review of exactly that head SHA. The script refuses unless its own files have the same content as `main`
of the public origin (exit 3), the PR is open, not a draft, based on `main` and headed by `<sha>` (exit 5), and every context the live ruleset
lists is verified on `<sha>` (exit 4): the ruleset must list at least one; `check`, `scan`, `images-gate`, `docs-gate`, `ui-check` must be
successful in the newest `pull_request` run of `ci.yml`, `security.yml`, `build-images.yml`, `docs.yml`, `ui.yml` that belongs to this PR;
`pruefstand/gate` is verified (success by `pruefstand-bot[bot]`) **only if the ruleset lists it**, which it does not today (owner: D5, after T6.2b),
so today a gated PR can merge without tier 2; any other listed context is unverifiable and refused. It then squash-merges with
`--match-head-commit` and posts one "merged by lead" comment. It refuses with exit 3 ("owner merge required") when the changes touch an
owner-merge path (renames and deletions included; casefolded): `.github/workflows/**`, `.github/actions/**`, any `CODEOWNERS`, `.github/dependabot.yml`, `infra/gpu/pruefstand-cluster`, `infra/gpu/install-cluster-wrapper.sh`, `infra/gpu/*.sh`, `infra/vm/**`, `infra/cluster/**`, `infra/gate-executor/**`, `**/sudoers*`, `security.yml`, `.gitleaks*`, `.gitleaksignore`, `.claude/**`, `docs/ops/secrets.md`, `scripts/merge_reviewed.sh`, `scripts/merge_paths.py`, `scripts/hooks/**`, `scripts/lead/**`. The owner merges those, including any change to the script itself.
Never `--admin`. The refusal is advisory: without the admin bypass, `uv run gh pr merge <n> --squash` can still merge an owner-path PR once the
checks are green (0 approvals, no code-owner review). Git's own configuration (`url.insteadOf`, `GIT_CONFIG_COUNT`) and bash's lazy reading of the script file are trusted.

## 10. Lead helper scripts (D1230)

`scripts/lead/` holds the helpers (nothing lives only in `/tmp` or `~/.local/lead-bin` any more); the folder is an owner-merge path because the wrappers run `origin/main`'s copy with the lead's rights.
`draft_push.sh [--dry-run] [--add <path>]... <worktree> <branch> <title> <msg-file> <body-file>` (ruff check + format check, commit, plain push of exactly that branch, DRAFT PR against `main`),
`draft_update.sh [--dry-run] [--add <path>]... <worktree> <branch> <msg-file>` and `resolve_merge.sh [--dry-run] <worktree> <branch> [pytest args...]`. Staging: tracked changes plus the
`--add` paths; other untracked files, files over 1 MB and secret-looking names (`.env`, `*.pem`, `id_*`, ...) are refused. A message, body, title or any commit message of the branch (`origin/main..HEAD`, checked before every push, also when nothing is staged) with a `Claude-Session:` line or a
"Generated with/by Claude Code" footer is refused (exit 2); a refusal never leaves files staged. `resolve_merge.sh` merges `origin/main` (a merge already in progress must be of `origin/main`), keeps both sides in `docs/decisions.md` (ONLY before PR #160 is on main: once `docs/decisions/` exists on `origin/main` it stops with `NEEDS MANUAL`
and the recipe `uv run python scripts/build_decisions_index.py --rebase-pending`) and the other append-only files, stops on other conflicts (every conflict under `docs/decisions/**` included), duplicate D-numbers and leftover markers; progress is in `<git-dir>/lead-resolve-merge.state` and a rerun resumes;
pytest runs in its own process group bounded by `LEAD_TEST_TIMEOUT` and dies with the script (after a SIGKILL of the script an orphaned pytest holds the lock until it ends or you kill the group named
`child_pgid` in the state file); `--dry-run` uses the local `origin/main` and does not fetch. They work from any cwd.

A worktree of a stale branch lacks `scripts/lead/`: call the wrappers instead. `scripts/lead/install_wrappers.sh` (run once from the main checkout, no sudo; `--dir` and `--main` override the
defaults) writes `~/.local/bin/lead-draft-push`, `lead-draft-update` and `lead-resolve-merge`; each fetches `origin/main` in the main checkout (`~/code/pruefstand`), fast-forwards it when it is a clean `main`
and execs that checkout's `scripts/lead/<name>.sh`. The old `/tmp/draft_push.sh` etc. symlinks are no longer needed. `make check` also runs `scripts/check_self_matching_pgrep.py`: never write
`pkill -f` / `pgrep -f` with a pattern that matches the calling shell or another session; use `pgrep -x`, `-P`, a PID file or the bracket trick (`pkill -f '[w]orker'`).
