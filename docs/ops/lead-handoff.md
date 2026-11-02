# Lead-agent handoff (written 2026-11-02)

Read this first if you are a new lead session. It states where the Wave 1-6 work stopped, what is open, what is
needed from the owner, and the working rules and traps. The authority order is unchanged: `CLAUDE.md`, then
`tasks/PARALLEL-PLAN.md` and `tasks/TASKS.md`, then this file (a snapshot, delete it when stale).

## 1. State of main

Merged (squash) and green: T0.1-T0.4, T0.7 (#6, VM setup), T1.1-T1.8, T2.1-T2.4, T1.13 (#24), plus fixes #18, #23
(`stack-run` signals), #25, #26 (gitleaks canary allowlist), #27 (`vm_check.sh`), #28 (T0.7 evidence). Repo is
public; ruleset on `main` is active (PR required, 0 approvals, linear history, required checks `check` and `scan`).

## 2. Open PRs at the time of writing (check live state with the API, not this list)

| PR | Branch | What | State when this was written |
| --- | --- | --- | --- |
| #29 | `feat/T4.4-perturb-deterministic` | T4.4 deterministic perturbations | CI green; round-2 re-review was running. Merge if the review has no major in {gate correctness, security, data integrity}. |
| #30 | `feat/T1.9-report` | T1.9 PR comment + JSON report + publisher | CI green; round-2 security re-review was running (canary masking, publisher). |
| #31 | `fix/cluster-probe` | T0.6 probe fixes (binary lookup, cold-load FAIL) | Review round 1 found 3 majors (redaction not fail-closed, wrong process executed, unload not guaranteed); the fixes were being written, head may not be pushed yet. Needs a re-review before merge. |
| #32 | `ci/unique-aggregator-names` | job names `images-gate` and `docs-gate` (were both `build`) + D400 (T0.5 settings) | CI running; fresh review running. After merge the owner adds `images-gate` and `docs-gate` as required checks. |

Local worktrees (VM, `~/code/wt/*`): T1.9, T4.4, ci-job-names, fix-probe (+ review scratch trees `review-pr32`, `rr2-pr29`,
`rr2-pr30*`, safe to `git worktree remove --force`). Remove a worktree after its PR merges.

Decision-number plan (append-only `docs/decisions.md`): D379 = probe fix (#31), D380-D387 = T1.9 (#30), D390-D394 = T4.4 (#29),
D400 = T0.5/job names (#32). D388-D389 and D395-D399 are free. Whoever merges later renumbers on collision.

## 3. What is needed from the owner

1. Re-run the T0.6 cluster probe once #31 is merged (`infra/cluster/feasibility/README.md`), then `summarise.py`. Without
   the verdict **T3.1a, T3.1b and T3.2 are blocked**. Commit the final `probe-<date>.out` only after checking it for hosts,
   IPs, ports and usernames; fill `docs/engineering/gpu-cluster.md` section 0.2 C1-C8 and the Decision line.
2. After #32 merges: add `images-gate` and `docs-gate` to the ruleset's required checks.
3. T0.5 leftovers (deliberately later, with T6.2a/T6.2b): the `pruefstand-bot` App and the `gate-router` environment.
4. Every sudo step is an owner step (the agent sudoers file is removed). Any change to the VM firewall, tunnel or systemd
   units is the owner's merge.

## 4. What is next (order from `tasks/PARALLEL-PLAN.md`)

- Finish Wave 6: T1.9 (#30), T4.4 (#29), then T3.2 (needs T3.1a). T3.1a/T3.1b wait for the probe verdict.
- Then Wave 7 (T1.10 pipeline+CLI, T3.3), Wave 8 (T1.11, T2.5, T5.1), Wave 9, ... Check each task's `Depends` cell in
  `tasks/TASKS.md` is merged before starting it; one task = one worktree = one branch = one PR.
- Follow-up tasks recorded in `tasks/TASKS.md` (not started): T1.7a/T1.7b (gate minors, `redact_evidence` normalisation),
  T1.8a, T1.9a, T1.13a, T2.3a, T2.4a, T4.4a. Do them after the main line, or fold into the owning wave.

## 5. Working rules that were in force (owner instructions)

- Lead orchestrates, task agents implement (Sonnet), reviews use Opus. At most 3 task agents at once. Stop agents when
  their PR merges. No polling or sleep loops: after a push start ONE `gh pr checks <PR> --repo dheena18/pruefstand --watch`
  in the background (do NOT pipe it: a pipe hides its exit code) and act on its exit.
- Merge yourself (squash, `--match-head-commit <full sha>`) when: CI green on the current head, the fresh-session review has
  no open blocker/major, main is merged in, and wave order is respected. Report each merge in one line.
  Review cap: at most 2 re-review rounds; after that a major blocks only if it touches gate correctness, security or
  data integrity (everything else becomes a follow-up task row + PR Follow-ups). Blockers always block.
- Still the owner's: VM firewall/tunnel/systemd/sudo changes, GitHub settings and rulesets, the private repo, anything under
  `/var/lib/pruefstand` or `/home/pruefstand`.
- Secrets: run project scripts that need `~/code/pruefstand/.env` only inside a subshell; never print, copy or commit values;
  never put tokens on a command line. The repo is public: no real IPs, cluster address/port, usernames, or `.env` content.
- Never add a "Generated with Claude Code" (or similar) footer to PR text, comments, issues or reviews. Commit trailers are fine.
- No force pushes; take main with `git merge origin/main` (or `gh api -X PUT repos/dheena18/pruefstand/pulls/N/update-branch`).
- Push only after `make check` exits 0 (check the exit status, do not chain a push after a failing check).

## 6. Traps found

- Use `env -u GITHUB_TOKEN -u GH_TOKEN gh ...` on the VM. `gh pr merge` needs the FULL head sha.
- `ruff` caches hide import-sort errors locally: run `uv run ruff check --no-cache .` and `ruff format --check --no-cache .`.
  After merging a PR that adds a dependency, run `uv sync --all-packages --all-extras` before `make check`.
- A PR-body edit can trigger a duplicate `ci` run that gets cancelled; the cancelled run's aggregate `check` shows as failed in
  `gh pr checks`. Judge by the latest `ci` run (`gh api repos/.../actions/runs?head_sha=<sha>`).
- A conflicting PR gets no workflow runs (no checks reported): merge main first.
- `scripts/tests/test_docker_mk_stack_run.py` signal cases are load-sensitive and fail under `nohup` (it ignores SIGHUP): run
  `make check` under `setsid` or from a normal ssh session, and re-run flaky tests alone before blaming a PR. Known timing
  flakes: `test_citation_forms.py::test_runs_in_linear_time`, `metrics/test_review2_hardening.py::...budget_is_shared...`.
- gitleaks scans all refs: a fake secret on any branch fails every PR's `scan`. Synthetic canaries are allowlisted narrowly
  in `.gitleaks.toml`.
- Do not `pkill -f` a pattern that also matches your own ssh command line.
- Cluster/GPU work only through `pruefstand-lock` (owner-run until sudo steps exist); never edit `MAINTENANCE`.
