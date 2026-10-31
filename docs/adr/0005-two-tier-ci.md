# 0005 — Three-tier CI: hosted code checks, hosted live CPU gate, A40 gate in a private executor repo that pulls work

- Status: Accepted (revised 2026-10-28: round-1 R2, round-2 Q2, round-4 real-stack tier 1; revised 2026-10-31: round-8 W1 tier-1 shape, W2 executor operations; revised round 9: X2.1–X2.8 lock order, `gate-router.yml`, fork SHA check, head-SHA builds, registry isolation, encrypted backups, cluster-disk baselines; X1.4/X3.11/X5.6 tier-1 decision scope; revised round 10 (D196–D208): executor on the TrueNAS VM `pruefstand-exec`, the cluster runs only Ollama reached through an `autossh` tunnel (one server for both GPUs since ADR-0018), `llm-proxy`, tier-2 budgets PR ≤ 90 min / nightly ≤ 5 h with generator/judge overlap; revised round 11 (D211–D229): one service user `pruefstand` with the host-wide lock `/var/lib/pruefstand/gpu.lock`, rootful Docker with accepted risk C18, `llm-proxy` on `gate-net` + `proxy-egress` reached as `http://llm-proxy:11500` (D242), night window 22:00–06:00 with a refusal stratum + 1 of 3 stratified blocks (≤ 600 cases), 15-min heartbeat, infra failure ⇒ `error` + one retry, NAS automount, laptop backup receipt; revised round 13 (P1, D287–D289): `pruefstand/gate` pinned to the `pruefstand-bot` App, `gate-router.yml` posts with the App token from environment `gate-router`, the only tier-2 PR trigger is the owner's `workflow_dispatch`, the `run-gate` label and PR poll are removed; P2 (D290): nightly guard output + `if:`)
- Amended by: [ADR-0018](0018-single-ollama-server.md) (2026-10-31: one Ollama server for both GPUs, port 11434 only)
- Date: 2026-10-27
- Tasks: T0.2, T0.5, T0.6, T0.7, T1.11, T1.12, T1.13, T3.1a, T6.2a, T6.2b

## Context
The real gate needs a 27B-class generator, BGE-M3, a reranker and an LLM judge. Hosted runners have no GPU.
On a **public** repo, a self-hosted runner is reachable by any workflow file a PR brings along
(for `pull_request`, the workflow comes from the PR head), so `if:` conditions and labels inside
workflow files are not a security boundary. Round 2 also found that a dispatch credential in a public
environment is used by the PR's own copy of the workflow and would need `contents: write` on the
private repo — a path to code execution on the A40s. The design must be operable by one person.
Round 8 found that (a) a 2B CPU model with an uncalibrated free-tier judge cannot carry a
statistical required check in ≤ 30 min, (b) an ephemeral runner needs a fresh registration token
every hour, and (c) one shared concurrency group silently cancels pending nightly and promotion runs.
Round 9 found that (d) making the A40 runner post "not gated" for every PR blocks even docs-only PRs
whenever the runner is busy or offline, (e) scripts that re-take the GPU lock inside a lock-holding job
deadlock, and (f) a fork result posted on the fork's *current* head can land on unreviewed code.
Round 10 (owner facts 2026-10-31, `docs/planning/reviews/round10-resolution.md`) found that the A40
cluster `cairo-s101lp` has a nearly full local disk, no confirmed Docker or vLLM, and no systemd linger,
and that the owner can run a TrueNAS VM that mounts the same NAS dataset as the cluster and can SSH to
it. So the cluster can host GPU inference but not the runner, containers or state.
Round 11 (`round11-resolution.md` Y1, Y4, Y5) found that the per-user lock, SSH key and tunnel unit did
not exclude anything across the VM's two users (executor and owner/agents), that the 5-h nightly plus
its extra jobs overran the night, and that an infrastructure fault during a run became a candidate
`failure`.
Round 13 (`round13-resolution.md` P1, A13-01) found that the VM's fine-grained token (pull requests and
Workflows write) could add the `run-gate` label as the owner and could push a branch workflow that posts
`pruefstand/gate` with `GITHUB_TOKEN`, which the source-unpinned required check accepted; and (P2, A13-02)
that a guard job which merely exits 0 still lets its dependent nightly job run.

## Decision
| Tier | Where | Runs | Trigger |
| --- | --- | --- | --- |
| 0 Code | public repo, GitHub-hosted `ubuntu-24.04` | lint, types, arch, pure unit tests on real inputs, doctests, statistical validation (reduced grid), cassette replay, contract + integration (real Qdrant, real rag-demo, llama.cpp), docker build + Trivy, docs, UI tests; `build-images.yml` pushes the rag-demo image by digest and signs it (cosign keyless) | every push and PR, forks included |
| 1 Live | public repo, GitHub-hosted CPU runner (4 vCPU / 16 GB), `live-e2e.yml` | **real stack** (ADR-0008): Qdrant + rag-demo + llama.cpp generator (≤ 2B, Q4_K_M, thinking off) + CPU embeddings on the real 5-law slice; `pruefstand run --config examples/live/pruefstand.yaml --tier pr` on split `smoke_live` (20 cases); the required check decides on **hard fails and `error_rate` only** (X5.6); language, citation, refusal checks and `injection_success` (n = 2, X3.11) are reported, not gating; PRs compare only to artefact `live-baseline` (push-to-main runs), nightly 40-case runs write `live-baseline-nightly` (X1.4); judged metrics informational (≤ 10 GitHub Models calls per PR, skipped on quota exhaustion or for forks); bug-switch scenario matrix nightly and on rag-demo PRs (deterministic outcomes only); budget ≤ 20 min, `timeout-minutes: 30`; real PR comment; Action self-test on the same stack | every PR (forks without judge), push to `main`, nightly |
| Router | public repo, GitHub-hosted, `gate-router.yml` on `pull_request_target`, **no checkout**, job permission `pull-requests: read` only, environment `gate-router` with the `pruefstand-bot` App key (deployment branch `main`; X2.2, round 13 P1.1) | reads the PR's changed files from the API; posts with the App token: no gated path (or only release-exempt lines) → `pruefstand/gate` = success "not gated"; otherwise `pending` "gated: awaiting tier-2 dispatch" | `opened`, `synchronize`, `reopened` |
| 2 Gate | **private** repo `dheena18/pruefstand-gate`, self-hosted **persistent** runner on the **TrueNAS VM `pruefstand-exec`**, running as the system user `pruefstand` (runner, orchestrator, rootful Docker, Qdrant, candidate, `rerank-cpu`, `llm-proxy`, lock `/var/lib/pruefstand/gpu.lock` + state on the VM disk; Y1); GPU inference on the A40 cluster through the `pruefstand-tunnel.service` (`autossh`) tunnel to **one** Ollama server on `:11434` that serves both GPUs (ADR-0018; generator + `bge-m3` on one card, the judge on the other, placed by Ollama) | `gate-executor.yml` (PR tier, **≤ 90 min**), `baseline-promote.yml` (main + nightly promotion), `nightly.yml` (**≤ 8 h**, 22:00–06:00 Europe/Berlin, refusal stratum + one of 3 stratified blocks of `full`, ≤ 600 cases; weekly cause-switches; Y4.3), `backup.yml`; the statistical gate | PR gates: **only** the owner's `workflow_dispatch` of `gate-executor.yml` (input `pr`, browser or GitHub mobile app; P1.2); `baseline-promote.yml` polls `main`; nightlies by schedule |

1. **No self-hosted runner on the public repo, and no secret in it** that reaches the executor. There is
   no dispatch workflow. The single `pull_request_target` workflow is `gate-router.yml` (X2.2, P1.1): no
   checkout, no PR code, `pull-requests: read`, environment `gate-router` holding the `pruefstand-bot` App
   key (deployment branch `main`; `pull_request_target` always runs the `main` version); the workflow guard
   (T0.2) allowlists exactly this file, asserts it has no checkout step and that no other workflow names that
   environment or `secrets.BOT_APP_*`.
2. `gate-executor.yml` has **only** `workflow_dispatch` (input `pr`, own concurrency group per PR,
   `${{ github.workflow }}-${{ inputs.pr || inputs.sha }}`; round 13
   P1.2): the owner starts it from the browser or the GitHub mobile app. The VM token cannot reach the private
   repo, so coding agents cannot start tier 2; there is no `run-gate` label and no PR poll. The executor gates
   the PR head **at dispatch time**, which must carry a `pruefstand/image` status; a new push needs a new
   dispatch; `state/processed.jsonl` (private branch `executor-state`) records each run. PRs with no gated
   path are left to `gate-router.yml`, which also posts success "not gated (release version bump)" for
   release-please PRs that only bump versions, the CHANGELOG and the member version lines in `uv.lock`
   ("not gated" comes only from there, P4.2).
3. **Trusted inputs only:** gate config (`pruefstand.yaml`), dataset, held-out canaries, judge config and
   the `pruefstand` package come from public `main` or the private repo, never from the PR. From the
   PR the executor takes only `apps/rag-demo/configs/rag.gpu.yaml` (X3.15) and the candidate image built
   by public `build-images.yml` **from the PR head SHA** (not the merge commit, X2.4), pulled **by
   digest** from the public GHCR package (no credential) and verified with `cosign verify` (identity
   regexp in `ci-cd.md` §7). The signature proves origin only; the candidate is treated as untrusted.
4. Fork PRs are gated the same way. Only the image build needs a same-repo branch: a maintainer runs
   `scripts/mirror_fork_pr.sh N`, which pushes `gate/pr-N` and opens **no** PR (refuses diffs touching
   `.github/**`, `infra/runner/**`, `infra/gate-executor/**`, `action/**` or
   `scripts/mirror_fork_pr.sh`), then the owner dispatches `pr=N`. At dispatch the executor reads the fork
   head SHA, gates `gate/pr-N` **only if** its head SHA equals it, and posts the status **to that SHA only**
   (X2.3, P1.2).
5. The candidate container runs on the VM and gets **no GPU and no internet egress**: it sits on the
   `--internal` Docker network `gate-net` with `qdrant` and `rerank-cpu`, and reaches the trusted
   **`llm-proxy`** (D206, D242: a normal container on `gate-net` and `proxy-egress`, reached as `http://llm-proxy:11500`; it reaches the tunnel at `172.17.0.1:11434`, firewalled to the `proxy-egress` subnet), its
   only route to Ollama: generator and embedding models only (ADR-0018), only the native `/api/chat`, `/api/embed`, `/api/tags`, only the run's
   catalogue generator and embedding tags; it enforces only `num_ctx` and `keep_alive` (catalogue
   values) and passes `temperature`, `seed`, `top_p`, `num_predict` through within the catalogue `option_bounds` (outside → 403)
   (round 12 N2); no admin API; the tunnel ports on `172.17.0.1` are firewalled in Docker's `DOCKER-USER`
   chain and in the dedicated `PRUEFSTAND-INPUT` chain hooked from `INPUT` (container → `172.17.0.1` hits
   `INPUT`), both applied by the oneshot `pruefstand-firewall.service` (N4.2, D285); no judge model is ever reachable (model allow-list; one server since ADR-0018). Containers started by user
   `pruefstand` through the rootful daemon; no host socket, no privileged containers, `--cap-drop ALL`,
   read-only root fs. The owner user (coding agents) is root-equivalent on the VM, an accepted risk for a
   dedicated VM (`security.md` C18). The held-out canary **registry** is
   never mounted into or reachable by the candidate; it sees only the corpus through Qdrant (X2.5).
6. **One gate App `pruefstand-bot`** (a separate `pruefstand-release` App exists only for release-please,
   see ADR-0017), installed on the public repo only (`statuses: write`, `pull_requests: write`,
   `contents: read`, `metadata: read`); its key lives in the private repo and in the public environment
   `gate-router` (deployment branch `main`, used only by `gate-router.yml`, P1.1). It posts the redacted PR
   comment and the commit status `pruefstand/gate` (from the executor for gated PRs, from `gate-router.yml`
   for "not gated" and the gated `pending`). The private repo uses its own
   `GITHUB_TOKEN`. Sanitised dashboard data (`main`) and `heartbeat.json` (branch `heartbeat`) go to a
   separate public repo `dheena18/pruefstand-dashboard-data`, pushed with a fine-grained PAT scoped to
   that repo only and stored in the private repo.
7. **Runner:** persistent, on the VM (never on the cluster), registered once by the owner, run as the
   system service `pruefstand-runner.service` as the system user **`pruefstand`** (Y1.1, D211), which also
   owns the cluster SSH key and the system unit `pruefstand-tunnel.service`; the runner service has
   `Wants=` + `After=mnt-pruefstand.automount` (never `Requires=`), the tunnel unit has no NAS dependency,
   and a missing mount fails the job in the preflight with `infra_error="nas_unavailable"` (round 12 N4.1). `ACTIONS_RUNNER_HOOK_JOB_STARTED` / `_COMPLETED` scripts
   wipe the workspace, remove job containers/networks/volumes and drop PR-scoped Qdrant collections and
   cache overlays.
8. **Concurrency and lock (X2.1):** one group per private workflow (`cancel-in-progress: false`), plus
   one group per dispatched PR. GPU mutual exclusion: the orchestrator takes
   `flock /var/lib/pruefstand/gpu.lock` (one host-wide path on the **VM's local disk**, never the NAS;
   D200, D211) **once per job** and exports `PRUEFSTAND_LOCK_HELD=1`; the owner and agents use the
   wrapper `pruefstand-lock <cmd>` on the same file (D212);
   `switch-mode.sh`, `health.sh` and `fetch-model.sh` (created by T3.1a) never take the lock and refuse
   to run without that variable. Order: `MAINTENANCE` check (file `/var/lib/pruefstand/MAINTENANCE`) → job selection → lock → **preflight**
   (`health.sh --repair`: tunnel ports, restart of a down Ollama server over SSH with `start-ollama.sh`,
   resident model digests, NAS mount; D208) → serve; lock timeout → `pending` "executor busy", preflight failure → `error` "executor unhealthy".
   An infrastructure failure **during** a run (Ollama down, tunnel lost, NAS unavailable, a model reload) → run
   `stop_reason="aborted"` with `infra_error`, status `error` (never `failure`), not recorded as
   processed, one automatic retry after `health.sh --repair` (Y5.2, D226).
   `nightly.yml` never dispatches `baseline-promote.yml`; the promote poll picks up the newest complete
   nightly run.
9. Required check: the commit status **`pruefstand/gate`** itself; the ruleset **pins** the context to the
   `pruefstand-bot` App (round 13 P1.1): both posters use that App, so a status posted with `GITHUB_TOKEN` by any
   branch workflow cannot satisfy it. No hosted `gate-required` job. A gated PR without a baseline for its eval fingerprint gets
   `failure` "no baseline for <fp>; run baseline-promote", never `success`. Escape hatch for an executor
   outage (VM, tunnel or cluster): the ruleset bypass list holds only the repository admin (the owner), used from
   the browser; a drill verifies that the VM token cannot use it (runbook §2 step 7); every bypass is logged
   in `docs/ops/bypass-log.md`.
10. **Health:** the orchestrator refreshes `heartbeat.json` every **15 min** while a job runs or waits on
    the lock (Y5.1, D225), on branch `heartbeat` of the dashboard-data repo; the public, hosted
    `executor-health.yml` (hourly) opens or updates an issue when it is older than 2 h. Weekly backup:
    one bundle (private repo + NAS baseline files, X2.7) `age`-encrypted **as a whole**, written to
    the NAS `backups/`, plus a mandatory weekly copy on the owner's laptop, confirmed by a receipt file
    that `backup-check` watches (> 8 days → issue `backup-stale`, Y5.5); the key lives only on the
    owner's laptop (X2.6, `docs/ops/runbook.md`).
11. **Budgets (round 10 Z4, D199; round 11 Y4, D222–D224):** tier-2 PR run ≤ 90 min (`robust_pr` via
    `/v1/retrieve` only, reranker top 10); nightly ≤ 8 h in the window 22:00–06:00 Europe/Berlin (two UTC
    cron entries; a hosted guard accepts the cron that matches the current Berlin offset, and one orchestrator job stops at the 06:00 deadline, round 12 N4.3), a fixed refusal stratum (all unanswerable cases, ≥ 100 clusters) plus one of 3 stratified blocks of
    `full` (≤ 600 cases; `full` covered every 3 nights, SPEC §6.2), cause-switches
    weekly; judge fallback ⇒ judged metrics informational; the first model load per mode from the NAS is
    excluded. If T3.1b measures more, PR runs pass `--judged-subset`: generation **and** judging of the
    `core` answerable cases on the fixed seeded 150-case judged subset (`TestCase.judged_subset`; retrieval
    metrics on all of `core`, deterministic security cases in full; round 13 P3.4; SPEC §7.2 MDE rows).
    Nightly = `--split full --stratum all --block auto` (refusal stratum + block k = `state/nightly_counter`
    mod 3, P4.4) gated vs baseline ref `nightly-b<k>`, drift vs `release-b<k>`; the hosted guard sets
    `run=true|false` and the nightly job runs only `if: needs.guard.outputs.run == 'true'` (P2.1); a hard
    06:00 Berlin deadline of the fired night is checked at start and before each phase (`window_exceeded`)
    and skipped nights are reported (round 12 N1, N4.3).
    The nightly judge runs on the other card than the generator (one server, ADR-0018), so nightly generation and judging
    overlap (D205).

Tier 1 needs no secret: `GITHUB_TOKEN` with `models: read` is the only credential, and GitHub gives
fork PRs none (their judged metrics are skipped, `judge_mode=skipped`). There is no CPU fallback judge:
an uncalibrated judge never decides a required check. Tier-1 numbers are a deterministic safety signal
from small CPU models; **tier 2 is the authoritative statistical gate** for merges touching gated paths.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Runner on the public repo with `if:`/label gating | A PR's workflow file can target the runner directly |
| Public `gate-dispatch.yml` + environment-held App token (round-1 design) | The secret is used by the PR's own workflow copy and needs `contents: write` on the private repo |
| Runner hook rejecting unknown `job_workflow_ref` | Workable, but one bug away from RCE |
| A40 runner posts "not gated" for every PR (round-8 design) | Docs-only PRs blocked whenever the single runner is busy (nightly, lock waits) or offline (R9-10) |
| Hosted private `gate-poll.yml` with the App key (R9-10 proposal) | Works, but costs private Actions minutes and puts a second consumer of the App key on a schedule; `gate-router.yml` needs no secret at all |
| Source of `pruefstand/gate` not pinned, posting limited by the workflow guard (round 9–12 design) | A branch workflow pushed with Workflows: write (the VM token has it) can request `statuses: write` and post the context with `GITHUB_TOKEN`; the guard only flags it after it ran (A13-01). Replaced by the App pin with `gate-router.yml` using the App token (P1.1) |
| `run-gate` label + 15-min executor poll (round 9–12 design) | The VM token (pull requests write) can add the label as the owner, so agents could start tier 2, incl. on fork PRs (A13-01). Replaced by the owner-only dispatch (P1.2) |
| Docker socket / privileged DinD in the job | Root on the host |
| Ephemeral runner re-registered per job (round-7 design) | Registration tokens expire after 1 h; ~200 jobs/day would need hourly manual token refresh |
| Separate `gate-runner` user with per-user lock, key and user tunnel unit (round-10 design) | Two lock files exclude nothing; the runner user could not use the owner's key or user unit (round 11 A11-01/-02) |
| Rootless Docker for the executor user | `llm-proxy` cannot reach the host tunnel through RootlessKit's namespace without host-loopback tricks (A11-05); the VM is dedicated, so rootful Docker + accepted risk C18 is simpler |
| Full `full` split every night, cause-switches nightly | 10–14 h per night on one runner; overruns the window and blocks the working day (A11-06) |
| Runner, Docker and Qdrant on the A40 cluster (round-9 design) | Cluster local disk nearly full, Docker/vLLM not available, `Linger=no` (round 10); the VM has Docker, systemd and the NAS |
| vLLM/TEI containers on the cluster | No Docker on the cluster; Ollama is installed and serves GGUF models from the NAS (ADR-0009, D198) |
| Expose Ollama on a cluster network port | Ollama has no authentication; loopback + SSH tunnel keeps it off the network (`security.md` C14) |
| JIT runner config with an `administration: write` PAT | A long-lived admin credential on the executor host; the hook-based persistent runner is enough for private trusted workflows |
| One shared `gpu-cluster` concurrency group (round-7 design) | A newer queued run cancels the pending one: nightly and promotion runs are silently lost |
| Tier-1 statistical gate with GitHub Models judge + CPU fallback (round-7 design) | n = 20 is underpowered, the free quota is too small, and the CPU fallback judge is uncalibrated |
| Everything on hosted runners / paid GPU runners | No GPU for 27B-class models / costs money while the A40s are available |
| Hosted tier with test doubles instead of live models | Rejected by the owner (ADR-0008): not evidence about real behaviour |

## Consequences
- Positive: no public credential reaches the executor; no code from a PR runs anywhere except inside an
  isolated, GPU-less, offline candidate container on the VM, and nothing of ours but the Ollama
  processes runs on the shared cluster. One gate App, no mirror PRs, no runner
  token chores. Tier 1 is fast, deterministic and never flaky; outages are noticed within about 2 h, and
  non-gated PRs never depend on the executor.
- Negative (round 9, round 13): one documented `pull_request_target` workflow exists and holds the App key
  (environment `gate-router`, deployment branch `main`); a branch workflow could still name a job like another
  required check run, so the merge step checks each required check's source workflow (`security.md` C13, C18).
- Negative: every tier-2 PR gate needs an owner action (a dispatch from the browser or the mobile app); two repos
  plus a public data repo to maintain; one PAT to rotate yearly; executor code synced at a maintainer tag
  `executor-<YYYYMMDD>` (`scripts/sync_executor.sh`; `v*` tags are reserved for the release App and
  trigger `release.yml`). Tier 1 no longer gates judged quality. Three machines (cluster, VM, NAS)
  and one SSH tunnel (port 11434, ADR-0018) must be up; the preflight repairs a down Ollama server (`setsid nohup`), a dropped
  tunnel is restarted by `autossh`/systemd, a TrueNAS reboot is recovered by VM autostart and the NAS
  automount. Development agents share the executor VM and are root-equivalent there (accepted, C18). On the shared cluster, Ollama on loopback is reachable by other local
  users (accepted risk, `security.md` C14). If the T0.6/T0.7 feasibility check is no-go, the same
  VM-side design runs against a rented 48 GB GPU host with one Ollama server.
