# Lead-agent handoff (updated 2026-11-02)

Read this first if you are a new lead session. It states where the work stopped, what is open, what is needed from the
owner, and the working rules and traps. The authority order is unchanged: `CLAUDE.md`, then `tasks/PARALLEL-PLAN.md` and
`tasks/TASKS.md`, then this file (a snapshot, delete it when stale).

## 1. State of main

Merged (squash) and green: T0.1-T0.4, T0.7, T1.1-T1.9, T1.13, T2.1-T2.4, T4.4, plus the fixes for the `stack-run` signals
(#23), the `vm_check.sh` false FAILs (#27), the T0.6 probe (#31), the unique aggregator job names (#32), the T0.7 evidence
(#28) and the gitleaks canary allowlists. The repo is public; the ruleset on `main` is active (PR required, 0 approvals,
linear history). Required checks: `check`, `scan`, `images-gate`, `docs-gate`.

No PR is open at the time of writing (check live state with the API, not this file). Decision numbers in use on main run
to D400; take the next free number when adding a row and renumber on collision.

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

- Wave 6 left: T3.2 (needs T3.1a). Then Wave 7 (T1.10 pipeline+CLI, T3.3), Wave 8 (T1.11, T2.5, T5.1), Wave 9, Wave 10.
  Check each task's `Depends` cell in `tasks/TASKS.md` is merged before starting it; one task = one worktree = one branch =
  one PR. Work on tasks that do not need the T0.6 verdict while it is pending.
- Follow-up task rows recorded in `tasks/TASKS.md` (not started): T1.7a, T1.7b (gate `redact_evidence` normalisation: same
  two canary-masking fixes as the report layer), T1.8a, T1.9a, T1.13a, T2.3a, T2.4a, T4.4a.

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
- Cluster/GPU work only through `pruefstand-lock` (owner-run; agents have no sudo); never edit `MAINTENANCE`.
