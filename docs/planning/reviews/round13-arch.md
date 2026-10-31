# Round 13: cold read 8, architecture + DevOps/security lens

Reviewer stance: principal architect + DevOps/security engineer, reading the pack cold against the
**real** setup (binding): VS Code on Windows → Remote-SSH into the TrueNAS VM `pruefstand-exec` (64 GB,
rootful Docker, service user `pruefstand`, `autossh` system unit without NAS dependency, `DOCKER-USER` +
`PRUEFSTAND-INPUT` firewall chains, `llm-proxy` on `gate-net` + `proxy-egress`); the cluster `cairo-s101lp`
runs only two Ollama servers (`setsid nohup`), models on the NAS; the NAS is mounted on both.

Read: `CLAUDE.md`, `docs/decisions.md` (superseded rows ignored), `docs/architecture/*.md`, `docs/adr/*.md`,
`docs/engineering/{ci-cd,docker,security,gpu-cluster,release,git-workflow}.md`, `docs/ops/*.md`,
`.env.example`, `tasks/TASKS.md`, `tasks/PARALLEL-PLAN.md`, `prompts/_lead-agent.md`, prompts T0.0–T0.7,
T1.12, T1.13, T3.1a, T3.1b, T6.1, T6.2a, T6.2b, T8.5, T9.1a, T9.1b. Prior findings: `round12-arch.md`,
`round12-resolution.md` (N1–N7), `round12-integration.md` (D284–D286). Only items that are still open or
new are reported. **No file other than this one was edited.** Line numbers refer to the files at the time
of this read.

Counts: **0 blockers, 3 majors, 11 minors** (14 findings).

## Verified (no finding)

- Round-12 majors applied: tunnel without NAS dependency, runner `Wants=`/`After=mnt-pruefstand.automount`,
  one unit name, N4.1 [HUMAN] variant in T0.7 (A12-01); firewall via `pruefstand-firewall.service`
  (`PartOf=`/`WantedBy=docker.service`), `DOCKER-USER` + `PRUEFSTAND-INPUT`, no `flush ruleset`, behavioural
  probes incl. an `--internal` egress probe and a Docker-restart probe (A12-02, D285); cron-string guard on a
  hosted runner, single orchestrator job, 06:00 deadline per phase (A12-03, see A13-02); fine-grained
  public-repo token with `gh-scope` check (A12-04, see A13-01); `docs.yml` `pages` group on the deploy job
  only (A12-05).
- Round-12 minors applied: retry state + 315-min PR timeout (M1), `*_false_since` / `last_nightly_at`
  (M2, see A13-M3), `run/` pid dir + `/proc` check (M3), lock-bound wrapper ops (M5), stale lines in
  runbook/deployment/lead prompt (M6), `id-token` allowlist (M7), D277 wording (M10), monthly
  schedule-active check (M11), `--repair` normalisation (M12). M8 and M9 are moot (D260, D261).
  M4 is applied twice in incompatible ways (A13-M6).
- Mermaid: all 35 fenced blocks under `docs/` (planning reviews and the archived SPEC-v1 excluded) re-scanned:
  no `;` or `#` in sequence/state messages, every flowchart label and edge label with special characters
  quoted, no bare `end` tokens. Braces in two sequence messages (`sequences.md:387,389`) are legal.
  Topology in deployment §3, gpu-cluster §1 diagram, ci-cd §2.1–§2.5 and sequences matches the binding setup
  (candidate only on `gate-net`, proxy on `gate-net` + `proxy-egress` → `172.17.0.1:11434`, tunnel as a
  system unit of `pruefstand` with no NAS edge, Ollama only on the cluster, lock/state on the VM disk). One
  stale prose line remains next to the gpu-cluster diagram (A13-M7).
- Pages chain: `docs.yml` deploys only on `workflow_run` with a provenance check (`deploy.yml`, `head_branch
  == main`, allowed events, success), so a branch run of a modified `deploy.yml` cannot publish.
- Qdrant on `gate-net`: collection-scoped key or per-job Qdrant (T6.2a sandbox list).
- Release: tag ruleset on `refs/tags/v*` with only the release App as bypass actor; `pypi` and
  `huggingface` environments have a required reviewer; cosign identity pinned to the tag ref.

## Findings

| ID | Sev | Where | Finding | Fix |
| --- | --- | --- | --- | --- |
| A13-01 | major | docs/engineering/security.md:66 (C18: agents "cannot label `run-gate`, merge with `--admin`"), :46 (P2: CODEOWNERS review of `.github/` limits who can post `pruefstand/gate`); docs/ops/secrets.md (VM token row); docs/ops/runbook.md:172-173 ("the VM token cannot bypass"); prompts/T0.7-truenas-vm-setup.md:118 (`gh-scope` checks only fine-grained prefix, `permissions.admin`, 404 on `pruefstand-gate`); prompts/T0.5-github-setup.md:58 (bypass = Repository admin, the owner); prompts/_lead-agent.md:79-81 (the lead merges with `gh pr merge --squash` after the owner's "merge <PR>") | **The N4.4 token does not remove the GitHub-side powers that C18 says it removes, and nothing tests the two that matter.** (1) *Label:* the token has Pull requests: write, which is enough to add labels to a PR. The label is then applied by the owner's account, so `select_jobs` accepts it as an allowlisted maintainer's `run-gate`. That includes fork PRs, where the label is the human approval for running foreign code on the executor. (2) *Statuses:* the token has Workflows: write (D284). An agent can push a branch whose workflow runs on `push` with `permissions: statuses: write` (requested in the YAML, so the read-only default does not stop it) and posts `pruefstand/gate` = success on that branch's head. The context is required without a pinned source (X2.2). The same workflow can name a job like a required check. P2's CODEOWNERS mitigation has no effect, because the ruleset requires 0 approvals and no code-owner review. `check_workflows.py` only flags the PR after the rogue workflow has already run. (3) *Bypass:* ruleset bypass is evaluated per actor, and the owner is the bypass actor. Nothing in the pack shows that a fine-grained token without Administration loses it, and `gh-scope` does not probe it. The runbook and C18 state it as fact. (4) The owner's merge decision relies on the lead agent's report that "CI is green". The impact is bounded by C18, which already accepts that an agent can tamper with executor state. But the security doc now claims a boundary that does not exist, and the check meant to prove it misses the cases above. | Correct C18/P2 and runbook §2.7: the VM token **can** label `run-gate` and **can** make a branch workflow post statuses. Either accept that explicitly (the candidate sandbox stays the boundary) or mitigate. Mitigations: (a) the owner merges in the browser, or the lead's pre-merge step checks via the API that the `pruefstand/gate` status `creator` is `pruefstand-bot[bot]` (gated PR) or `github-actions[bot]` from `gate-router.yml` (`target_url` → that workflow), and that each required check run comes from its expected workflow file; (b) for fork PRs the executor also requires the fork to be mirrored by `mirror_fork_pr.sh --reviewed` (already true), and C18 says that this human step is the real approval. Add a `gh-scope` probe for bypass: on a throwaway PR with a required check failing, `gh pr merge --admin` from the VM must be refused. If it is not refused, empty the bypass list and handle outages by temporarily disabling the ruleset in the browser, which needs Administration that the token lacks. Drop the CODEOWNERS claim from P2. |
| A13-02 | major | prompts/T6.2b-gate-workflows.md:113 (`guard`: "the wrong-season cron exits 0 without posting"; `nightly` `needs: guard`), :191 (`test_check_workflows.py`: exactly two jobs, no `if:` asserted), :193 (no late-start-after-06:00 case); docs/engineering/ci-cd.md:200 ("the other one exits 0"; job named `night-guard`, `timeout-minutes: 480`), ci-cd.md §2.3 diagram (`G -- no --> EXIT`) | **Both crons start a nightly every night, because the guard's "skip" is a successful job.** A job with `needs: guard` runs whenever `guard` succeeds. Exiting 0 does not stop it. Every night the off-season cron (an hour later) queues a second `nightly.yml` run. Because the `nightly` group has `cancel-in-progress: false`, it waits and starts when the first run ends. One of two things follows. (a) It finds less than one phase before 06:00, records `last_nightly_status = "aborted: window_exceeded"` or `skipped: …`, and overwrites the real night's status, so `executor-health.yml` opens `nightly-skipped` every night. (b) If the first run ended early, it runs a second gate on the same block, then a second drift, prune and promotion candidate. The diagram in ci-cd §2.3 shows the intended behaviour, but the workflow spec does not produce it. A related gap: a `nightly` job that only starts after 06:00 (the runner was busy with a 315-min PR or promote job) must use the **fired night's** 06:00, not the next 06:00. Otherwise it runs a full nightly during the day. The job names and timeouts also differ: `guard` with `nightly` ≤ 470 (T6.2b) versus `night-guard` with `nightly` = 480 (ci-cd), and the T6.2b budget test sums both. | `guard` sets an output (`run=true\|false` from `night-guard`), and `nightly` has `if: needs.guard.outputs.run == 'true'`. `test_check_workflows.py` asserts that `if:`. `night-guard` also returns the night's deadline (06:00 Berlin of the date of the fired schedule instant), and `gate-orchestrator nightly --deadline <iso>` uses it. A start at or after the deadline posts `skipped: late start`. Add `test_nightly.py` cases: off-season cron → `run=false`; fired 20:07 UTC but the job starts at 06:20 Berlin → no phase runs, `skipped: late start`. Use one job name (`guard`) and `timeout-minutes` (`nightly` 470) in ci-cd §1.2, T6.2b and `test_budgets.py`. |
| A13-03 | major | docs/engineering/security.md:50 (D4); docs/architecture/deployment.md §5; prompts/T8.5-deploy-cd.md (`cloudflared` on `demo-net`); prompts/T0.7-truenas-vm-setup.md:58-62 (NAS share NFS **or** SMB, choice open), :83-85 (firewall rules cover only `172.17.0.1:11434/11435`) | **The public-facing demo network has unrestricted LAN egress from the VM's own address.** `demo-net` cannot be `--internal`, because `cloudflared` needs outbound internet. So every demo container (rag-demo with public input, Qdrant, llama.cpp) can open connections into the LAN, NATed to the VM's IP. That includes the TrueNAS host (web UI and, if T0.7 picks NFS, the export that trusts the VM's IP: a userspace NFS client inside a container is enough, no mount and no `CAP_SYS_ADMIN` needed) and the cluster's SSH, which still accepts the password login (T0.7 Context). An RCE in the demo app therefore reaches the NAS dataset: `bin/` scripts that run on the shared cluster, baselines, backups and models. D4 only checks that `llm-proxy`, `172.17.0.1:11434` and the gate Qdrant are unreachable, and that no NAS is **mounted**. Only applies once T8.4/T8.5 are built (optional). | Put the demo app containers on an `--internal` `demo-net` and attach only `cloudflared` to a second egress network `demo-egress` (fixed subnet, created like `proxy-egress`). In `pruefstand-firewall.sh`, add `DOCKER-USER` rules that drop `demo-egress` → RFC 1918/LAN (except DNS if needed), and drop `demo-egress`/`demo-net` → VM host ports in `PRUEFSTAND-INPUT`. Extend the D4 checks: from the rag-demo container, the NAS IP (2049/445/443), the TrueNAS UI and `cairo-s101lp:22` are unreachable; from `cloudflared`, only the internet is reachable. Record in T0.7 that the NFS export is restricted to the VM address **and** that containers never reach the LAN (or prefer SMB with credentials). |
| A13-M1 | minor | prompts/T0.5-github-setup.md:97-99 (Interfaces: environments `demo, preview (no reviewer, same-repo branches)`, "demo tokens in `demo`"), :79 (S10: "no issue is opened anywhere (D91)") | Stale after D244/D261 and D256/D275. S13 itself says to create no `demo`/`preview` environment, and `executor-health.yml` opens `executor-down`, `backup-stale`, `nightly-failed` and `nightly-skipped`. A human following the Interfaces block would create the two environments. | Remove `demo, preview` and the demo-token note from the Interfaces block. Reword S10: "the App opens no issue (no `issues: write`); the public `executor-health.yml` opens the health issues". |
| A13-M2 | minor | prompts/T9.1a-release-pipeline.md:110 (S5: environments `pypi`, `testpypi` without settings); docs/engineering/release.md:39-40 (only `pypi`/`huggingface` get a reviewer); docs/ops/secrets.md:53 | `testpypi` has no reviewer and no deployment-branch rule. With Workflows: write on the VM token (D284), any agent branch can add an `on: push` job with `environment: testpypi` and `id-token: write`. The trusted publisher matches repo + `release.yml` + environment, not the ref, so that branch can publish under the project's TestPyPI name. | Environment `testpypi`: deployment branches `main` only (RC dispatches run from `main`), or the owner as required reviewer. Note it in release.md §2 and T9.1a S5. |
| A13-M3 | minor | docs/architecture/interfaces.md:802-803 and docs/engineering/ci-cd.md:74 (`last_nightly_status` = `"completed"` \| …) vs prompts/T6.1-baseline-store-cache.md:121, T6.2a:216, T6.2b:137/:197 (`"ok"`, issue closes on `== "ok"`); docs/ops/runbook.md:150 (`skipped: lock`, `skipped: runner offline`) vs T6.2b:113 (`skipped: runner busy`, `skipped: preflight <reason>`); ci-cd:200 (`last_nightly_at` unchanged on a skip) vs T6.2b:193 (skip sets `last_nightly_at`) | The heartbeat vocabulary is not one contract. If T6.1 follows interfaces (`completed`) and T6.2b follows its prompt (`ok`), `nightly-skipped` never closes. The runbook names reasons that nothing emits. `runner offline` cannot be written by the runner at all. | One value set in interfaces §7: `ok \| failed \| aborted: window_exceeded \| skipped: maintenance \| skipped: runner busy \| skipped: late start \| skipped: preflight <reason>`. Decide whether a skip updates `last_nightly_at` (recommended: no, so the 26-h watchdog still fires for a series of skips). Align ci-cd §1.1/§1.2, runbook §2 and the T6.1/T6.2b tests. |
| A13-M4 | minor | prompts/T6.2b-gate-workflows.md:128-136; interfaces.md:798-804 (no maintenance field); gpu-cluster §2 / runbook §2a.3 (datagen weekend stops both day servers and runs `ollama-all` on `:11434` only) | During every datagen weekend (and any planned `MAINTENANCE`), each poll job ends with a heartbeat in which `ollama_gpu1_ok=false`. After 2 h `executor-health.yml` opens `executor-down` and comments on it hourly, which trains the one maintainer to ignore the alarm. | Add `maintenance: bool` (file present) to the payload. `check_heartbeat.py` suppresses the health-field alerts while it is true but still alerts on a stale `ts`. Add one test row. |
| A13-M5 | minor | prompts/T6.2b-gate-workflows.md:150 (`release-full-due` = "first night after a new release tag"); ci-cd.md:200 (release night) | The release full run (≈ 5–7 h) gets no second chance. If that night is aborted (`window_exceeded`, an infra error: no in-job retry fits) or skipped (`MAINTENANCE`, busy runner), no `release` baseline exists. Every later drift phase then reports `INSUFFICIENT_DATA` with exit 0 until the next release, so the stated nightly purpose ("cumulative drift against the last release") is lost without notice. | State-based rule: `release-full-due` is true while the newest `v*` tag has no promoted `release` run for the current fingerprint. A drift phase without a `release` baseline sets a heartbeat/summary flag (`drift: no release baseline`) that `executor-health.yml` reports once. Add the test cases. |
| A13-M6 | minor | CLAUDE.md:137 and decisions D278 ("start stacks only through `make`; a raw `docker compose` binds the executor's default ports"); docs/ops/secrets.md (`*_PORT` "never in `.env`: exported by `make`") vs prompts/T0.3-docker-compose.md:82/:106, docker.md:109-112, gpu-cluster.md:341, runbook §0.7, PARALLEL-PLAN rule 7, deployment.md:53, ai-workflow.md:98 (`make ports-env` writes the ports into `.env` so raw compose is safe) | A12-M4 was applied twice in incompatible ways. Agents read CLAUDE.md ("never raw compose") and the secrets table ("never in `.env`"), while T0.3 builds `ports-env`, which writes exactly those keys into `.env`. | Keep `ports-env` (it covers the mistake D278 forbids) and update the secrets row (`*_PORT`: "written by `make ports-env` into the owner's VM `.env`; never in `runner.env`") and CLAUDE.md §3 / D278 to "prefer `make up`; raw compose is safe after `make ports-env`, verified by `make check-ports`". |
| A13-M7 | minor | docs/engineering/gpu-cluster.md:65 | Stale tunnel command: `autossh -L 11434:localhost:11434 -L 11435:localhost:11435 cairo-s101lp` (no `-M 0 -N`, no `ExitOnForwardFailure`, no `172.17.0.1` binds) next to the diagram that shows the four binds. Someone copying it for a manual tunnel loses the proxy path. | Replace with the T0.7 S5 command (four `-L` forwards, D242), or point to it. |
| A13-M8 | minor | tasks/PARALLEL-PLAN.md:42-47 (rule 7); prompts/_lead-agent.md:47-50 | All agent worktrees share one dev compose project (`COMPOSE_PROJECT_NAME=pruefstand-dev`, same `.env` symlink, fixed dev ports). `stack.lock` is taken per command. Agent B's `docker compose up` can therefore replace agent A's containers between A's `up` and A's Done-when checks (`docker compose exec`, curl on `:18000`), so A's evidence comes from B's build. | Define a stack session as one lock hold: `flock ~/pruefstand/stack.lock sh -c 'make up …; <checks>; make down'` (e.g. `make stack-run CMD=…`, T0.3). The lead's sub-agent rules say "hold the lock from up to down". |
| A13-M9 | minor | docs/engineering/gpu-cluster.md:330 and prompts/T6.2a-gate-executor.md (runner "pinned release + sha256", unit `ExecStart` unspecified) | The runner's update policy is undefined. With `--disableupdate`, GitHub stops assigning jobs to a runner more than about 30 days behind a new release, so the gate stalls until `executor-down` fires and someone updates it by hand. With auto-update, the unit must start `run.sh`/`runsvc.sh` (which restart the listener after an update), not `Runner.Listener` directly. | T6.2a: auto-update on; `ExecStart` = the runner's `run.sh` (or the generated `svc.sh` unit); the pinned sha256 applies to the first install only. Runbook §6: compare heartbeat `runner_version` with the latest release. |
| A13-M10 | minor | docs/ops/runbook.md:249-258 (laptop steps use `rsync`, `ssh`, `sha256sum`, `$(…)` on the Windows laptop); prompts/T6.2b-gate-workflows.md:114 and ci-cd.md:201 (receipt written "through the TrueNAS share" / "pushes to the NAS") vs runbook (written over `ssh` into the VM as the owner user) | The mandatory weekly backup copy is written for a Linux shell, but the laptop is Windows, and WSL is optional (CLAUDE.md machines table). There are also two different receipt paths, and the single-writer table names "the owner's laptop". A missed copy raises `backup-stale` for a step the owner cannot run as written. | Give the Windows-native commands (PowerShell `scp`, `Get-FileHash -Algorithm SHA256`, receipt via `ssh … "cat > …"`), or make WSL mandatory for this step. Use one receipt path (over `ssh` to the VM, owner user, group `pruefstand`), and update T6.2b/ci-cd and the gpu-cluster §9 writer column. |
| A13-M11 | minor | prompts/T0.7-truenas-vm-setup.md:118 (`vm_check` `firewall`: "after `sudo systemctl restart docker` the same probes still pass"); docs/ops/runbook.md §2 ("then run `infra/vm/vm_check.sh`" after a host reboot), §0.3 | It is ambiguous whether `vm_check.sh firewall` restarts Docker itself. If it does, the routine recovery check in runbook §2 kills a running gate or nightly (with `Requires=docker.service` the runner restarts too) and loses up to 8 h of work. | `vm_check.sh` never restarts Docker. The restart probe is a separate `--restart-drill` flag that refuses while `gpu.lock` is held (`flock -n` succeeds only when free) and is used only for the T0.7 N4.2 Done-when. |

## Workflow triggers, permissions and required checks (summary)

| Workflow | Owner task | Trigger / permissions coherent | Note |
| --- | --- | --- | --- |
| `ci.yml`, `security.yml`, `cassettes.yml`, `live-e2e.yml` skeleton | T0.2 | yes | 60-day schedule check in runbook §6 |
| `build-images.yml` | T0.3 + T6.2b | yes | `gate/pr-*` mirrors refuse `.github/**` |
| `docs.yml` | T0.4 (+ T8.5) | yes | per-ref group, `pages` on the deploy job only, `workflow_run` provenance check |
| `live-e2e.yml` body, `action-selftest.yml` | T1.12 | yes | baseline only from `push` runs on `main` |
| `ui.yml` | T8.1/T8.3 | yes | `basepath-smoke` inside `ui / check` |
| `gate-router.yml`, `executor-health.yml` | T6.2b | yes | heartbeat vocabulary A13-M3, maintenance A13-M4 |
| private `gate-executor.yml`, `baseline-promote.yml`, `backup.yml` | T6.2b (orchestrator T6.2a) | yes | – |
| private `nightly.yml` | T6.2b | **no**: the guard skip does not stop the `nightly` job (A13-02) | release night A13-M5 |
| private `demo-nightly.yml` | T8.5 | same guard pattern, so the same `if:` is needed (A13-02) | demo egress A13-03 |
| `release-please.yml`, `release.yml` | T9.1a | yes | `testpypi` environment unprotected (A13-M2) |
| `deploy.yml` | T8.5 | yes | – |
| `dataset-release.yml` | T9.1b | yes | – |

Required checks (`ci / check`, `security / scan`, `build-images / build`, `docs / build`, `live-e2e / gate`,
`action-selftest / selftest`, `ui / check`, `pruefstand/gate`) are added only after their workflow exists,
and none of them is path-filtered or cancellable. Status and check-name spoofing by a same-repo branch
workflow is possible because of Workflows: write (A13-01).

## Security boundaries

| Boundary | State |
| --- | --- |
| public repo → private executor | OK: pull-only; `gate-router.yml` runs no PR code |
| agents (VM token) → GitHub | **overstated (A13-01)**: the token can label `run-gate` and, through a branch workflow, post `pruefstand/gate`; bypass not verified |
| owner/agents → executor on the VM | accepted (C18, root-equivalent) |
| candidate → models | OK: `gate-net` internal, proxy-only path, both firewall chains, behavioural probes |
| demo (public) → LAN/NAS/cluster | **open (A13-03)**: `demo-net` has LAN egress from the VM's address |
| VM → cluster | OK: key only under `pruefstand`, wrapper with tag regex and lock-bound mutating ops |
| VM/cluster → NAS | OK: single writer per path, `run/` listed; receipt writer unclear (A13-M10) |
| Pages / releases | OK: `workflow_run` provenance, tag ruleset, reviewed `pypi`; `testpypi` open (A13-M2) |

## Unattended operation (failure → recovery)

| Event | Recovery in the pack | Gap |
| --- | --- | --- |
| tunnel loss | system unit, `Restart=always`, preflight restart via sudoers | – |
| Ollama crash / cluster reboot | preflight `--repair` relaunches with `setsid nohup` and normalises the mode set | – |
| NAS outage / late export | automount, `Wants=` only, preflight `nas_unavailable`, V7b drill | – |
| Docker restart | firewall oneshot re-applied (`PartOf=`) | `vm_check` restart ambiguity (A13-M11) |
| VM / TrueNAS host reboot | autostart, automount, V7 drill | – |
| nightly | cron-string guard, one job, per-phase deadline | double nightly per night, late start after 06:00 (A13-02); release night not retried (A13-M5) |
| runner software | persistent runner, 14-day re-registration note | update policy undefined (A13-M9) |
| detection | heartbeat every 15 min, stateless `*_false_since`, four issue types | vocabulary mismatch (A13-M3); false `executor-down` in datagen (A13-M4) |
| backups | NAS + mandatory laptop copy, receipt, restore drill | Windows laptop steps (A13-M10) |

## One-person operability and parallel build safety

The runbook names the user for every command, has drills for the lock, infra failure, host reboot, NAS
late export, Docker restart, window and restore, and keeps admin actions in the owner's browser. Once
A13-02 is fixed, the nightly alarms are trustworthy. Without the fix, the `nightly-skipped` issue fires
every night and A13-M4 adds weekend noise, which is the main operability risk for a single maintainer.
The parallel-build rules are sound (ownership, shared hunks, `.env` symlink, `pruefstand-lock`, dev
ports, RAM budget). Two gaps remain: the lock scope of the shared dev compose project (A13-M8) and the
two contradictory port rules (A13-M6). The lead agent's merge step should verify where statuses came
from, not only that they are green (A13-01).
