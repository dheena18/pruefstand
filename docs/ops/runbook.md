# Operations runbook

Recurring and incident procedures for the private gate executor and its satellites, for one
maintainer. Design: ADR-0004, ADR-0005, `docs/engineering/ci-cd.md` §1.2 and §7; topology, cluster
commands and paths: `docs/engineering/gpu-cluster.md` §1, §4, §8, §9 (round 10, D196–D208; round 11 Y1–Y7,
D211–D239; round 12 N1–N5 and the `round12-arch.md` minors; round 13 P1–P5 and the `round13-arch.md` minors). This is the
**single** runbook (D145): first-time install of the VM and runner is §0 (T0.7, T6.2a); cluster and
Ollama operations are §2a (T3.1a); the dashboard deploy, the optional demo and their rollback are §9 (T8.5). Owners of the steps
below: T0.7 (VM, data root, SSH key, tunnel), T3.1a (cluster scripts, models), T6.2a (runner,
orchestrator, `llm-proxy`), T6.2b (workflows, health, backups), T8.5 (dashboard-data consumer).

**Where things run (Z1) and as whom (Y1).** Every command below runs **on the VM `pruefstand-exec`**
(VS Code Remote-SSH terminal) unless it says otherwise. Each command names its user: **[owner]** = your
login user (groups `pruefstand`, `docker`), **[pruefstand]** = the executor's system user
(`sudo -u pruefstand -i …`), **[root]** = `sudo`. GPU work by you always goes through
`pruefstand-lock <cmd>` (lock `/var/lib/pruefstand/gpu.lock`). You never hold the cluster key: **every
command of yours that needs the cluster goes through the sudo wrapper** (T3.1a, D247)
`sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster <op>` (ops `start-ollama`,
`stop-ollama`, `status`, `log [N]`, `pull|rm|show <tag>`; anything else exits 64). The cluster
`cairo-s101lp` runs only **one** Ollama server for both GPUs (ADR-0018; `127.0.0.1:11434`); it is reached from the VM by key-only SSH as
`pruefstand`, which calls the scripts as `ssh "$CLUSTER_SSH_HOST" bash $CLUSTER_DATA_ROOT/pruefstand-bin/<script>.sh`
(the wrapper does exactly that for you). `pruefstand-cluster log [N]` prints the last N (default 200, max 1000) lines of the Ollama log, redacted on the cluster and read-only (no lock); it is how you read the model load lines (slots, KV cache, offload). On the cluster only the models (`$CLUSTER_DATA_ROOT/Models`), these scripts and
`$CLUSTER_DATA_ROOT/ollama.log` are stored (ADR-0019); the server is started by your `~/start-ollama.sh` (setup log §7).
**Owner step:** the start script of record must exist at `~/start-ollama.sh` on the cluster (a link to your real script is
fine) and must set every value of `cluster.env`; `status.sh` and `health.sh` report a missing or non-executable one as a
WARN row `start-script`.

| Variable (VM `.env`) | Value |
| --- | --- |
| lock dir (fixed, not a variable) | `/var/lib/pruefstand/` (mode 2770, group `pruefstand`): `gpu.lock` (0660), `MAINTENANCE` |
| `PRUEFSTAND_HOME` | executor: `/home/pruefstand/pruefstand` (`runner.env` of user `pruefstand`) on the **local VM disk**: `state/`, `runner/`, `runs/`, `qdrant/`, `pruefstand-cache/`; your own `.env`: `~/pruefstand` (dev state only) |
| `PRUEFSTAND_DATA_ROOT` | `/mnt/pruefstand` (plain directory on the VM disk, ADR-0019, setup log §6): `data/`, `corpus/`, `datasets/`, `baselines/`, `backups/`, `cache/`, `logs/` |
| `CLUSTER_SSH_HOST` | `cairo-s101lp` (the public alias; the real host, user and port live only in `/home/pruefstand/.ssh/config`) |
| `PRUEFSTAND_CLUSTER_DATA_ROOT` / `/etc/pruefstand/cluster-data-root` | the cluster data root `$CLUSTER_DATA_ROOT` used throughout these docs (T3.1c, D950): the real path is **not in this repo**. Owner step, once: `sudo install -d -m 0755 -o root -g root /etc/pruefstand && echo '<absolute data root on the cluster>' | sudo tee /etc/pruefstand/cluster-data-root >/dev/null && sudo chmod 0644 /etc/pruefstand/cluster-data-root`, then check `stat -c '%U:%G %a %n' /etc/pruefstand /etc/pruefstand/cluster-data-root` (expect `root:root 755` and `root:root 644`). One line, plain ASCII `[A-Za-z0-9_./-]`, at most 4096 characters, no `..`, no trailing `/`. The file is used only when it is a regular file (no symlink) owned by root, not group/world-writable, in a root-owned directory that is not group/world-writable; otherwise exit 78. `sudo`, the executor and `health.sh` read the file; **set only the file for the service user** (do not export the variable in `runner.env`: the variable wins over the file). An interactive owner shell may use the variable instead. Below it: `Models/`, `pruefstand-bin/` (+ `-dev`), `ollama.log`. `deploy-cluster-bin.sh` and `install-cluster-wrapper.sh` exit 78 until it is set |
| `OLLAMA_GPU0_URL` / `OLLAMA_GPU1_URL` | both `http://127.0.0.1:11434` (the one tunnel end; generator lane / judge lane, ADR-0018) |
| `PORT_OFFSET` | your `.env` only: `10000` (dev stack ports, `docker.md` §3); never set for `pruefstand` |
| `PRUEFSTAND_GH_MODELS_TOKEN` | your `.env` only: the Models: read PAT for GitHub Models calls (D333); never named `GITHUB_TOKEN` |

Never export your `.env` wholesale into a shell that runs `gh`: an exported `GITHUB_TOKEN`/`GH_TOKEN` overrides gh's stored
login and `gh` loses repo/Actions access (HTTP 404 on `actions/runs`). If one is set, run `env -u GITHUB_TOKEN -u GH_TOKEN gh …`.

`dheena18` = your GitHub account.

## 0. First-time install of VM, tunnel and runner (T0.7, T6.2a fill in the exact commands)

Already done on 2026-10-31 (commands in `docs/ops/setup-log.md`): user `pruefstand`, the cluster key and the
alias `cairo-s101lp` (step 2), and `pruefstand-tunnel.service` with the `127.0.0.1:11434` forward (step 3, first
half). Re-run those steps only to rebuild the VM.

1. **VM** (T0.7, `[HUMAN]`): create `pruefstand-exec` on TrueNAS (Ubuntu 24.04, ≥ 8 vCPU, **64 GB RAM**,
   ≥ 200 GB local disk) with **autostart on host boot** (after the sharing service); VS Code Remote-SSH
   from Windows. [root]: rootful Docker; system user and group `pruefstand`; your login user in groups
   `pruefstand` and `docker` (group `docker` = `pruefstand` + you only, Y1.3); `/var/lib/pruefstand`
   (2770, group `pruefstand`) with `gpu.lock` (0660); the wrapper `/usr/local/bin/pruefstand-lock`
   (`flock` on that file, exports `PRUEFSTAND_LOCK_HELD=1`); one `sudoers` line allowing `pruefstand` to
   run `systemctl restart pruefstand-tunnel`, and the wrapper line for you (`pruefstand-cluster`, with
   `Defaults env_keep += PRUEFSTAND_LOCK_HELD`, so its mutating ops can prove you hold the GPU lock, A12-M5);
   firewall: inbound SSH only; the tunnel port on `172.17.0.1` (`11434`) accepts connections only
   from the `proxy-egress` subnet (step 3); `llm-proxy` has **no** host port (A12-M6). Data root (ADR-0019,
   **done**, setup log §6): `/mnt/pruefstand/{data,corpus,datasets,baselines,backups,cache,logs}` as a plain
   directory on the VM disk, owner `pruefstand`, mode 2775, no NFS and no mount unit; TrueNAS **Data Protection →
   Periodic Snapshot Tasks** on the VM zvol (daily, keep 14). **GitHub on the VM** (N4.4, `security.md` C18), [owner]: create a fine-grained token in the
   GitHub UI limited to `dheena18/pruefstand` (contents + pull requests + workflows write, nothing else; Workflows is required to push `.github/workflows/**`, D284; no access
   to `pruefstand-gate` or `pruefstand-dashboard-data`), `gh auth login --with-token` + `gh auth setup-git`,
   never `gh auth login --web`; check `gh api repos/dheena18/pruefstand-gate` → 404. Tier-2 dispatches, bypasses,
   merges and private-repo actions: only from your browser or the GitHub mobile app (what the token can do: §2 step 7).
   Run the bypass drill of §2 step 7 once.
2. **SSH key to the cluster** (T0.7 V5, Z7, Y1.1; **done**, setup log §2), [pruefstand]:
   `ssh-keygen -t ed25519 -N '' -f /home/pruefstand/.ssh/id_ed25519_cluster`, then
   `ssh-copy-id -i /home/pruefstand/.ssh/id_ed25519_cluster.pub -p <cluster-ssh-port> <cluster-user>@<cluster-ssh-host>`
   and the alias `cairo-s101lp` in `/home/pruefstand/.ssh/config` (`HostName`, non-default `Port`, `User`,
   `IdentityFile`; placeholders in git, real values only on the VM). If the cluster's home folder is
   group-writable, sshd ignores `authorized_keys`: `chmod g-w ~` on the cluster (setup log §2). You type the cluster
   password **once, interactively**; it is never written to `.env`, a file, GitHub or a NAS share. Check:
   `ssh -o BatchMode=yes cairo-s101lp true` succeeds. The private key stays only in
   `/home/pruefstand/.ssh` (mode 600).
3. **Tunnel** (T0.7 S5; the unit with the `127.0.0.1` forward already runs, setup log §3), [root]:
   `infra/vm/install-tunnel.sh` rewrites the **system** unit `pruefstand-tunnel.service` (`User=pruefstand`,
   `autossh -M 0 -N -o ExitOnForwardFailure=yes -L 127.0.0.1:11434:localhost:11434
   -L 172.17.0.1:11434:localhost:11434 cairo-s101lp`, port 11434 only, ADR-0018; `Wants=` and `After=network-online.target
   docker.service`, `Restart=always`, `RestartSec=10`; no storage dependency, ADR-0019; D242).
   [root] `infra/vm/setup-proxy-net.sh` creates the Docker network `proxy-egress` (`10.231.0.0/24`) and
   installs the oneshot **`pruefstand-firewall.service`** (`After=docker.service`, `PartOf=docker.service`
   so it is re-applied on every Docker restart), which inserts into Docker's **`DOCKER-USER`** chain (container-to-container and egress) **and** into the
   dedicated chain **`PRUEFSTAND-INPUT`** jumped to from `INPUT` (container → `172.17.0.1` is delivered
   locally and hits `INPUT`, not `DOCKER-USER`): accept `172.17.0.1:11434` from `10.231.0.0/24`,
   drop them from everything else (N4.2, D285). Never
   enable the distro `nftables.service`, never `flush ruleset`, never `systemctl restart nftables`: that
   deletes Docker's own rules, including the isolation of the `--internal` `gate-net`. Check after a VM
   reboot: `curl -s 127.0.0.1:11434/api/tags`; `ss -ltn | grep 11434` shows only `127.0.0.1` and
   `172.17.0.1`; `infra/vm/vm_check.sh firewall` (rules in `DOCKER-USER` and `PRUEFSTAND-INPUT`, Docker's chains present,
   no egress from a throwaway `--internal` container). `vm_check.sh` **never restarts Docker** (a restart would kill a
   running gate or nightly); the Docker-restart probe is the separate `infra/vm/vm_check.sh --restart-drill`, which
   refuses while `gpu.lock` is held (`flock -n` must succeed) and is used only for the T0.7 N4.2 Done-when (A13-M11).
   If the optional demo runs (T8.4/T8.5), the same service also installs the demo rules (round 13 P2.2): the
   demo app containers sit on the `--internal` network `demo-net` (`10.232.0.0/24`), only `cloudflared`
   (`10.232.0.2`) is also on `demo-egress` (`10.233.0.0/24`), `DOCKER-USER` drops `demo-egress` → `10.0.0.0/8`,
   `172.16.0.0/12`, `192.168.0.0/16`, and `PRUEFSTAND-INPUT` drops both subnets → the VM's own addresses and ports.
4. **Cluster scripts and models** (T3.1a), [pruefstand] from its trusted `main` checkout:
   `infra/gpu/deploy-cluster-bin.sh` copies `infra/cluster/*.sh` and the rendered `cluster.env` (Y6.3) over SSH to
   `$CLUSTER_DATA_ROOT/pruefstand-bin/` on the cluster (+ `SHA256SUMS`; ADR-0019); `fetch-model.sh` pulls `bge-m3` and the
   judge `gemma3:12b` into `$CLUSTER_DATA_ROOT/Models` (§2a.4; ≥ 2 GB must stay free); reuse or start the one server (§2a.1).
5. Private repo `dheena18/pruefstand-gate`, secrets `BOT_APP_ID`, `BOT_APP_KEY`, `DASHBOARD_DATA_PAT`. Public repo
   (round 13 P1.1), in your browser: environment **`gate-router`** (deployment branches: `main` only, no reviewer) with
   the same `BOT_APP_ID` / `BOT_APP_KEY`, used only by `gate-router.yml`; the `main` ruleset requires
   `pruefstand/gate` **with source = App `pruefstand-bot`** (pinned). Environment `testpypi`: deployment branches
   `main` only (A13-M2).
6. Persistent runner registered **once** on the VM under `/home/pruefstand/pruefstand/runner` (label
   `a40`), hook scripts in its `.env`, **system** service `pruefstand-runner.service` (`User=pruefstand`,
   no storage dependency, ADR-0019) (D100, Y1.1). Never on the cluster.
7. `llm-proxy` (`gate-net` + `proxy-egress`, `http://llm-proxy:11500`, D242), `rerank-cpu` and Qdrant (profile `gpu`) on the VM as
   `pruefstand` (T3.1a, T6.2a); ports in `docker.md` §3. Your dev stack uses `PORT_OFFSET=10000`; run
   `make ports-env` once so even a raw `docker compose … up` binds the dev ports, and `make check-ports`
   to confirm no dev container sits on a default port (A12-M4).
8. Branches `baselines` (protected) and `executor-state` created; first `baseline-promote.yml` run.

## 1. Moving parts

| Part | Where | Health signal |
| --- | --- | --- |
| Persistent runner (D100) | VM: `/home/pruefstand/pruefstand/runner`, system service `pruefstand-runner` (user `pruefstand`) | runner "Idle"/"Active" in the private repo settings; `heartbeat.json` age |
| Tunnel (T0.7) | VM: system unit `pruefstand-tunnel` (`autossh`, user `pruefstand`, port 11434 only) | `curl -s 127.0.0.1:11434/api/tags` |
| Ollama server (T3.1a, ADR-0018) | cluster: **one** server on `127.0.0.1:11434` for both GPUs (the running server is reused; only if none runs the scripts start your `~/start-ollama.sh` detached with `setsid nohup`, log `$CLUSTER_DATA_ROOT/ollama.log`, pid found by `pgrep` and checked against `/proc/<pid>/cmdline` and `:11434`, A12-M3); every mode is API loads/unloads on it; `OLLAMA_MODELS=$CLUSTER_DATA_ROOT/Models` on the cluster disk (ADR-0019) | [owner] `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status` (CSV: server env, card per model), `/api/ps` through the tunnel (`size_vram == size`) |
| VM services | rootful Docker on the VM, executor stack (user `pruefstand`): `qdrant` (`:6333`), `rerank-cpu` (`gate-net` only, no host port), `llm-proxy` (`gate-net` + `proxy-egress`, no host port; upstream `172.17.0.1:11434`, firewalled to `proxy-egress`); your dev stack on `+10000` ports | `docker ps`; `GET /readyz`, `GET /health` (proxy: also upstream error counters) |
| Data root (ADR-0019) | VM `/mnt/pruefstand`, a plain directory on the VM disk (zvol, TrueNAS snapshots) | `sudo -u pruefstand test -w /mnt/pruefstand && df -h /mnt/pruefstand` (≥ 20 GB free); sentinel `.pruefstand-data-root` |
| Cluster model disk (ADR-0019) | `$CLUSTER_DATA_ROOT/Models`: generator, `bge-m3`, `gemma3:12b` | `$C status` (free space on `/data`, ≥ 2 GB) |
| Executor workflows | private repo `dheena18/pruefstand-gate`: `gate-executor.yml` (**dispatch only**, input `pr`; you start it from the browser or the GitHub mobile app, P1.2), `baseline-promote.yml`, `nightly.yml` (hosted job `guard` with output `run` + one orchestrator job `nightly` with `if: needs.guard.outputs.run == 'true'`, 06:00 deadline of the fired night, P2.1), `backup.yml`, optional `demo-nightly.yml` (one concurrency group each, dispatches per PR, D101) | Actions tab of the private repo; heartbeat `last_nightly_at`, `last_nightly_status` |
| Firewall (N4.2) | VM: oneshot `pruefstand-firewall.service` (rules in Docker's `DOCKER-USER` chain + own `PRUEFSTAND-INPUT` chain from `INPUT`, D285) | `systemctl status pruefstand-firewall`; `iptables -S DOCKER-USER`; `iptables -S PRUEFSTAND-INPUT`; `infra/vm/vm_check.sh firewall` |
| Gate router (X2.2, P1.1) | public `gate-router.yml` (hosted, `pull_request_target`, no checkout, environment `gate-router`) posts with the `pruefstand-bot` App token: "not gated" for non-gated PRs, `pending` "gated: awaiting tier-2 dispatch" for gated ones | Actions tab of the public repo |
| GPU lock (X2.1, D200, D211) | `/var/lib/pruefstand/gpu.lock` (`flock`) on the **VM disk**, one file for every user, taken once per job by the orchestrator or by `pruefstand-lock <cmd>`; `switch-mode.sh` / `health.sh` / `fetch-model.sh` refuse to run without `PRUEFSTAND_LOCK_HELD=1` | `sudo fuser -v /var/lib/pruefstand/gpu.lock` shows the holder; the lock is advisory (`PRUEFSTAND_LOCK_HELD`/`PRUEFSTAND_LOCK_DIR` are unauthenticated, the lock's file descriptor is inherited by daemons started under it, exit codes 64/75/2 can collide with the command's; `infra/vm/README.md`) |
| Processed state (D102) and block counter (P4.4) | branch `executor-state`: `state/processed.jsonl` (a record of dispatched runs, not a trigger) and `state/nightly_counter` (block = counter mod 3, incremented only after a completed nightly) | last line = last gated run; counter grows by one per completed nightly |
| Baselines (X2.7, D209) | files in the data root `$PRUEFSTAND_DATA_ROOT/baselines/<fp>/{main,nightly-b<k>,release-b<k>,history/<run_id>}/`; branch `baselines` holds only `baselines/index.json` (ADR-0004) | `index.json` newest entry matches a directory in the data root |
| Dashboard data + heartbeat (D108, D109) | public repo `dheena18/pruefstand-dashboard-data` (`main`: data; branch `heartbeat`: `heartbeat.json`) | `heartbeat.json` timestamp (refreshed every 15 min during jobs), `<field>_false_since`, `last_nightly_at`, `last_nightly_status`, `maintenance`, `drift_no_release_baseline`, `runner_version`; `executor-health.yml` issues `executor-down`, `backup-stale`, `nightly skipped`, `nightly-failed` |
| Backups (X2.6, Y5.5) | data root `$PRUEFSTAND_DATA_ROOT/backups/<date>/pruefstand-gate.bundle.tar.age` (inside the TrueNAS zvol snapshots) + your laptop (mandatory weekly, receipt `backups/laptop-receipt.json`) | `backup.yml` run status; `backup-check` / heartbeat `laptop_backup_age_days` ≤ 8 |

## 2. Executor outage (VM, runner, tunnel, data root or cluster)

Symptoms: issue `executor-down` opened by `executor-health.yml` (heartbeat older than 2 h, or a health
flag false for more than 2 h by its `<field>_false_since`; health-field alerts are suppressed while the heartbeat
says `maintenance: true`, e.g. a model swap, A13-M4), issue `nightly skipped` (no nightly for
> 26 h, or `last_nightly_status` = `skipped: …` / `aborted: window_exceeded`), gated PRs stuck at
`pending` (incl. "executor busy (GPU lock held); re-dispatch"), or `pruefstand/gate` = `error` "executor unhealthy:
<reason>" / "executor infra error: <summary>; retrying once" (an infra failure mid-run, Y5.2), or
"executor infra error: <summary>; re-dispatch to retry" (the retry failed too, A12-M1).
Non-gated PRs are not affected: `gate-router.yml` posts their status on a hosted
runner.

1. [owner] On the VM: `systemctl status pruefstand-runner pruefstand-tunnel`;
   `journalctl -u pruefstand-runner -n 200` (both are system units).
2. `sudo fuser -v /var/lib/pruefstand/gpu.lock` (who holds the lock?); `df -h /home/pruefstand`;
   `sudo -u pruefstand test -w /mnt/pruefstand && df -h /mnt/pruefstand`; `curl -s 127.0.0.1:11434/api/tags`; GPU use: [owner] `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status`
   (someone else on the cards?). If the lock is free, run the preflight in report mode, [pruefstand]:
   `pruefstand-lock infra/gpu/health.sh` (from the executor's trusted checkout)
   (exit codes 10–16, incl. 15 = a resident model not fully on the GPU, `interfaces.md` §1.5).
3. Fix the cause:
   - runner: [root] `systemctl restart pruefstand-runner`;
   - tunnel: [root] `systemctl restart pruefstand-tunnel`; if it still fails, [pruefstand] `ssh -o BatchMode=yes
     cairo-s101lp true` (key rejected → §7 key rotation; host down → wait, the cluster is not ours);
   - Ollama down (e.g. after a cluster reboot; `Linger=no`, so nothing restarts it on the cluster):
     the next job's preflight (`health.sh --repair`) starts one server with `setsid nohup` (never a second one, ADR-0018); to do it by hand see
     §2a.1. If it dies again after you log out, check `KillUserProcesses` (T0.6 C4) and ask the admins;
   - resident digest ≠ catalogue (exit 13; someone pulled or replaced a tag on the shared store,
     `security.md` C14): re-run `fetch-model.sh <id>` under the lock (§2a.4);
   - data root unusable (exit 16, `infra_error="data_root_unavailable"`, ADR-0019): `/mnt/pruefstand` missing,
     not writable by `pruefstand` or < 20 GB free. Fix ownership (`sudo chown -R pruefstand:pruefstand
     /mnt/pruefstand`) or free space (`runs-prune`, old `backups/`, `cache/`); nothing to restart afterwards;
   - cluster model disk nearly full (`$C status` WARN, < 2 GB free on `/data`): an extra model is left over
     (RQ2 candidate, someone else's pull); remove it with the swap rule (§2a.4), never the generator;
   - **TrueNAS host rebooted** (update): the VM autostarts, tunnel and runner come up on their own (T0.7 V7); check
     step 1, then run `infra/vm/vm_check.sh` (it never restarts Docker; `--restart-drill` is a separate,
     lock-guarded flag, A13-M11);
   - **Docker restarted or the firewall looks wrong**: `systemctl status pruefstand-firewall` (it re-runs
     after every Docker start); never fix it with `nftables.service` (step §0.3);
   - **an extra model is resident** (a job was killed before its `finally`, e.g. an e5 or RQ2 candidate is
     still loaded): nothing to do; the next preflight's `health.sh --repair day` unloads every non-mode model first
     (A12-M12). By hand: `pruefstand-lock infra/gpu/switch-mode.sh day`;
   - **nightly skipped or stopped at the deadline** (`nightly skipped` issue): read the reason in
     `last_nightly_status` (the one value set, A13-M3: `ok`, `failed`, `aborted: window_exceeded`,
     `skipped: maintenance`, `skipped: runner busy`, `skipped: preflight <reason>`); a runner that was offline
     writes nothing and shows up only through the 26-h watchdog (`last_nightly_at` is not updated by skips). A
     long `baseline-promote` or PR gate around 22:00 only shortens the night; a job that only starts after
     06:00 of its night ends at once with `aborted: window_exceeded`, reported once for that night (P2.1). The
     block counter is not advanced by a skipped or aborted night, so that block simply runs on the next night
     (P4.4). If it repeats, move the work or dispatch `nightly.yml` by hand the next evening; the issue closes
     on the next nightly with status `ok`;
   - **`drift: no release baseline`** (heartbeat `drift_no_release_baseline`): the release anchor
     `release-b<k>` is missing for the current fingerprint (new tag, judge/metric change, aborted or flagged
     release run); the next night runs the release run of all of `full` again and `baseline-promote.yml`
     promotes it to `release-b0..b2` (D321; flagged runs are never promoted), nothing to do unless it persists
     for more than two nights;
   - **runner software outdated** (A13-M9): the runner auto-updates (unit `ExecStart` = the runner's
     `run.sh`/generated `svc.sh` unit, which restarts the listener after an update); if heartbeat
     `runner_version` lags the latest release, [root] `systemctl restart pruefstand-runner` and check the log;
   - **VM offline > 14 days**: GitHub has removed the runner; re-register once, [pruefstand]
     `./config.sh` with a new registration token in `/home/pruefstand/pruefstand/runner`, hooks
     unchanged;
   - disk: `docker system prune --filter until=168h` (never volumes); the nightly `runs-prune` keeps
     run dirs bounded;
   - the other GPU user: wait. If a stale lock holder is dead, `flock` releases on its own; never
     delete `gpu.lock` while a process holds it.
4. Planned work: [owner] `touch /var/lib/pruefstand/MAINTENANCE` first (dispatched gates then post `pending`
   "executor in maintenance; re-dispatch later", the nightly posts success "skipped: maintenance", and
   `executor-health.yml` suppresses the health-field alerts), `rm` it afterwards.
   Model swaps (ADR-0019 swap rule, §2a.4) always run inside such a window. Note every skipped nightly in the PR
   or issue that caused it.
5. If `heartbeat.json` is stale but the runner is fine, check the PAT (§7): an expired
   `DASHBOARD_DATA_PAT` stops heartbeat pushes.
6. Back to normal: nothing re-runs by itself (there is no PR poll, P1.2). Re-dispatch every gated PR that is
   still `pending` or `error`, from the browser or the GitHub mobile app:
   private repo → Actions → `gate-executor.yml` → Run workflow → `pr = N` (a single infra failure is retried in
   the same job and is not recorded; a PR whose retry **also** hit an infra failure is recorded with
   `result: "error"`, A12-M1, and runs again only on your new dispatch). `executor-health.yml` closes the issue
   on the next fresh heartbeat.
7. **Merging while the executor is down:** only through the ruleset bypass (repository admin, from your
   browser), only for a real outage, and always with a row in `docs/ops/bypass-log.md` (D106). Re-run the
   nightly after recovery and record its result there.
   **What the VM token can and cannot do (round 13 P1.3, `security.md` C18).** The fine-grained token on the VM
   can push branches (incl. `gate/pr-N`), open and edit PRs, and push workflow files that then run on its
   branches and may post commit statuses with `GITHUB_TOKEN`. None of it can produce `pruefstand/gate` (the
   ruleset pins the check to the `pruefstand-bot` App; the App key is only in the private repo and in the public
   environment `gate-router`, deployment branch `main`) or start tier 2 (the only trigger is a dispatch in the
   private repo, which the token cannot see: `gh api repos/dheena18/pruefstand-gate` → 404). Before merging,
   check in the PR's checks tab (or let the lead agent check via the API) that `pruefstand/gate` comes from
   `pruefstand-bot` and that every other required check run comes from its expected workflow file; merge in the
   browser.
   **Bypass drill (once after T0.5/T0.7, and after every token or ruleset change):** open a throwaway PR whose
   required check fails, then on the VM run `gh pr merge <N> --admin --squash`. It **must be refused**. If it is
   not, empty the ruleset's bypass list in the browser and handle outages by temporarily disabling the ruleset
   (needs Administration, which the token lacks); record the result in `docs/decisions.md`.

## 2a. Cluster and Ollama operations (T3.1a scripts; all started from the VM)

Shorthand for you [owner]: `C="sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster"` (the T3.1a sudo
wrapper; it runs the fixed scripts in `$CLUSTER_DATA_ROOT/pruefstand-bin` over SSH with the cluster key of `pruefstand`,
D247). As [pruefstand] the scripts may also be called directly as
`ssh $CLUSTER_SSH_HOST bash $CLUSTER_DATA_ROOT/pruefstand-bin/<script>.sh`.
Every step that loads, unloads or pulls models runs under the GPU lock: `pruefstand-lock <cmd>` (waits on
`/var/lib/pruefstand/gpu.lock`).

1. **Start Ollama** (ADR-0018; idempotent): `pruefstand-lock $C start-ollama`. If a server already answers on
   `127.0.0.1:11434`, nothing is started. Only if none runs does the script start **your** start script of record
   (ADR-0019, setup log §7): `setsid nohup ~/start-ollama.sh > $CLUSTER_DATA_ROOT/ollama.log 2>&1 < /dev/null &` (Y5.4).
   Its settings: `CUDA_VISIBLE_DEVICES=0,1`, `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_MODELS=$CLUSTER_DATA_ROOT/Models`,
   `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_CONTEXT_LENGTH=8192`,
   `OLLAMA_NOPRUNE=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1`. It never starts a second server
   and refuses if `~/start-ollama.sh` is missing.
   **Server with other settings** (`$C status` shows WARN for `OLLAMA_*` env ≠ `cluster.env`): decide once,
   outside any gate run, under the lock: fix `~/start-ollama.sh`, then restart by hand on the cluster
   (`pkill -x ollama; sleep 3; setsid nohup ~/start-ollama.sh > $CLUSTER_DATA_ROOT/ollama.log 2>&1 < /dev/null &`,
   setup log §7); record the decision in `docs/decisions.md`. The wrapper's mutating ops (`start-ollama`,
   `stop-ollama`, `pull`, `rm`) refuse unless you hold the GPU lock (`pruefstand-lock …`, A12-M5);
   `status` and `show` work without it. Check: `$C status`; `curl -s localhost:11434/api/tags`.
2. **Stop**: normally not needed (unload models instead: `switch-mode.sh` or `keep_alive: 0`).
   `pruefstand-lock $C stop-ollama` stops the one server (pid from `pgrep -u <cluster-user> -x ollama`, used only
   if `/proc/<pid>/cmdline` is `ollama serve` and `:11434` listens, A12-M3). **Logs**: [pruefstand]
   `ssh $CLUSTER_SSH_HOST tail -n 200 $CLUSTER_DATA_ROOT/ollama.log`.
3. **Mode switch** (`gpu-cluster.md` §2): `infra/gpu/switch-mode.sh day|night` under the lock.
   Every mode only unloads/loads through the Ollama API on the one server (`keep_alive: 0` / `"24h"`, loads always
   with the catalogue `options` so the first real request does not reload; no server start or stop, ADR-0018);
   since ADR-0019 both modes load the same set (generator, `bge-m3`, the one judge `gemma3:12b` at `num_ctx`
   12288, D306: generator 8 192 + allowance ≤ 3 072 + 1 024 reserve; lower only if T3.1b's VRAM measurement
   failed). There is no `datagen` mode. The first load per mode comes from the cluster disk and is excluded
   from the budgets.
4. **Pull or update a model**: `infra/gpu/fetch-model.sh <models.yaml id>` under the lock:
   `ollama pull <tag>` on the cluster against the one server (store `$CLUSTER_DATA_ROOT/Models`), then the manifest
   digest is compared with `infra/gpu/models.yaml`; a mismatch removes the tag and exits 1 (D207). One pull at
   a time; it refuses when `/data` would keep < 2 GB free. **Swap rule** (ADR-0019; e.g. an RQ2 judge candidate):
   `pruefstand-lock touch /var/lib/pruefstand/MAINTENANCE`; `pruefstand-lock infra/gpu/fetch-model.sh --rm <id>`
   of a **non-generator** model; `pruefstand-lock infra/gpu/fetch-model.sh <new id>`; measure; remove it again and
   re-pull the standard model; `pruefstand-lock rm /var/lib/pruefstand/MAINTENANCE`. Never remove the generator.
5. **Card placement** (ADR-0018): `$C status` lists the card(s) of every resident model; `health.sh` exit 15 =
   a model not fully in VRAM (`size_vram < size`) or spread over both cards. Usually another
   process holds VRAM (`nvidia-smi` foreign pids) or a fourth model was loaded: unload the extra models with
   `switch-mode.sh <mode>` and re-run `health.sh --repair`.
6. **ngrok URL to Ollama** (rejected, `security.md` C19, setup log §5): Prüfstand never uses it. If it still runs
   on the cluster, stop it, or protect it (basic auth or an IP allow-list in its traffic policy) and rotate the URL.
7. **Deploy cluster scripts** after a change to `infra/cluster/**` on `main`, [pruefstand] from the
   trusted checkout only (development uses `$CLUSTER_DATA_ROOT/pruefstand-bin-dev/`): `infra/gpu/deploy-cluster-bin.sh`
   (copies over SSH, writes `*.partial`, then `mv`, plus `SHA256SUMS`; the orchestrator also runs it). `health.sh`
   exit 14 = `$CLUSTER_DATA_ROOT/pruefstand-bin` stale.
8. **Shared-cluster checks** (accepted risk `security.md` C14): `$C status` shows other processes on
   our cards; a resident digest that is not in the catalogue fails the preflight. Ask the cluster admins
   once whether per-user network namespaces or a loopback firewall exist and record the answer in
   `docs/decisions.md`.

## 3. Gated PR shows "no baseline for <fp>"

The PR's eval fingerprint has no `main` baseline yet (dataset release, judge or metric version bump, a
new Ollama model digest, D103). In the browser (or the GitHub mobile app) run `baseline-promote.yml` in
`dheena18/pruefstand-gate`, wait for it to finish, then dispatch `gate-executor.yml` with `pr = N` again.

## 3a. Main FAILs against the previous main after an accepted metric drop (owner only)

`baseline promote` refuses a run whose `gate.json` is FAIL or that has a hard-fail finding (D881), so after a merged,
knowingly accepted drop the new `main` run never becomes the baseline and every later PR gates against the old one.
Decide first that the drop is accepted (and that it is no leak: hard fails are never an accepted drop). Then, on the VM
as the owner and **by hand, never from a workflow**: `pruefstand baseline promote --run <run dir of main's run> --ref main
--allow-failed-gate --reason "<why the drop is accepted>" --config <pruefstand.yaml>` (the stored `override.by` is `GITHUB_ACTOR` or your OS user name: a label for the audit trail, not authentication) (under `pruefstand-lock` if it touches the data root while a job runs).
Note the run id and the reason in `docs/ops/bypass-log.md`. A missing or invalid `gate.json` (exit 1 / 3) is not waived,
nor is one decided against another run than the stored baseline (D1120): run `pruefstand gate` for the run first.

## 4. Fork PR

1. Review the diff on the fork PR.
2. `scripts/mirror_fork_pr.sh N` pushes the reviewed head to `gate/pr-N` (no PR is opened; the script
   refuses protected paths).
3. Wait for `build-images.yml` on `gate/pr-N` (status `pruefstand/image`).
4. Dispatch the gate (round 13 P1.2): private repo → Actions → `gate-executor.yml` → Run workflow →
   `pr = N` (browser or GitHub mobile app). Your review, mirror and dispatch are the approval for running the
   fork's code. At dispatch the executor reads the fork PR head SHA and gates `gate/pr-N` **only if** its head
   SHA equals it; the comment and `pruefstand/gate` go to **that SHA only** (X2.3).
5. If the fork author pushes again (or `gate/pr-N` was changed by anyone else), the run does not start
   ("fork head moved since mirroring"): review again, re-run step 2 and dispatch again. Delete `gate/pr-N`
   after merge or close.

## 5. Backups and restore drill (weekly / quarterly)

`backup.yml` runs every Sunday at about 06:00 UTC on the VM and writes **one** file to the data root,
`$PRUEFSTAND_DATA_ROOT/backups/<date>/pruefstand-gate.bundle.tar.age` (8 kept; written as `*.partial`,
then renamed): a tar of the `git bundle --all` of `pruefstand-gate` (incl. the held-out canaries) and of
`$PRUEFSTAND_DATA_ROOT/baselines/`, piped through `age -r <your public key>` (X2.6). There is no
plaintext copy and no separate canary file; the private key exists **only** on your laptop. The data root
itself is on the VM zvol, covered by the TrueNAS periodic snapshots (daily, keep 14; ADR-0019).

Weekly [HUMAN], on your **Windows** laptop in PowerShell (**mandatory**, Y5.5; `backup-check` opens the
`backup-stale` issue when the receipt is older than 8 days). Uses the built-in OpenSSH client (`scp`, `ssh`);
no WSL needed (A13-M10). The receipt has one path: written **over `ssh` into the VM as your owner user** (group
`pruefstand`), never through an SMB share:

```powershell
$dst = "$HOME\pruefstand-backup"; New-Item -ItemType Directory -Force $dst | Out-Null
$B = ssh <user>@pruefstand-exec "ls -t /mnt/pruefstand/backups | grep -v receipt | head -1"
New-Item -ItemType Directory -Force "$dst\$B" | Out-Null
scp "<user>@pruefstand-exec:/mnt/pruefstand/backups/$B/pruefstand-gate.bundle.tar.age" "$dst\$B\"
Get-ChildItem $dst -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 3   # newest weeks present
$h = (Get-FileHash -Algorithm SHA256 "$dst\$B\pruefstand-gate.bundle.tar.age").Hash.ToLower()
$t = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
"{`"bundle`":`"$B`",`"sha256`":`"$h`",`"copied_at`":`"$t`"}" |
  ssh <user>@pruefstand-exec "cat > /mnt/pruefstand/backups/laptop-receipt.json"   # receipt
```

Keep the `age` private key off the VM, TrueNAS and the cluster (password manager + offline copy).

Quarterly restore drill [HUMAN] (also the T6.2b Done-when), on your laptop in a Linux shell (WSL, or copy the
bundle to the VM's owner home and run it there; `age` and `uv` are needed):

```bash
mkdir -p /tmp/restore && cd /tmp/restore
age -d -i ~/.age/key.txt ~/pruefstand-backup/<date>/pruefstand-gate.bundle.tar.age | tar -x   # bundle + baselines/
git clone pruefstand-gate.bundle repo && ls repo/canaries/heldout | head
cat > /tmp/restore/cfg.yaml <<'EOF'
# copy of the gate config with only the store changed
baseline_store: {type: local_dir, path: /tmp/restore/baselines}
EOF
uv run pruefstand gate --candidate <run> --from-store --config /tmp/restore/cfg.yaml   # sha256 OK
file ~/pruefstand-backup/<date>/pruefstand-gate.bundle.tar.age                          # not a git bundle
```

`LocalDirBaselineStore` reads the restored disk layout unchanged (T6.1 test).

## 6. Monthly checks [HUMAN]

| Check | Command | Expected |
| --- | --- | --- |
| No self-hosted runner on the public repo (security C1) | `gh api repos/dheena18/pruefstand/actions/runners --jq .total_count` | `0` |
| Private repo size | `gh api repos/dheena18/pruefstand-gate --jq .size` | small and flat (index-only baselines, X2.7); the nightly `repo-size` guard fails above 1 GB |
| Baseline prune ran | first `baseline-promote.yml` run after 00:00 UTC on the 1st, step `baseline-prune` | success; ≤ 20 `history/` entries per fingerprint (D110): `ls $PRUEFSTAND_DATA_ROOT/baselines/*/history \| wc -l` |
| VM disk | `df -h /home/pruefstand` | runs + caches + Qdrant well below the disk size |
| Data root | `df -h /mnt/pruefstand`; `ls /mnt/pruefstand/backups \| wc -l` | ≥ 20 GB free; ≤ 8 backups; TrueNAS snapshot task ran (ADR-0019) |
| Cluster model disk | [pruefstand] `ssh $CLUSTER_SSH_HOST 'ollama list; du -sh ~/.ollama 2>/dev/null; df -h / /data'` | only the ADR-0019 set in `$CLUSTER_DATA_ROOT/Models`, ≥ 2 GB free on `/data`, no store in `~/.ollama` |
| SSH key login | [pruefstand] `ssh -o BatchMode=yes cairo-s101lp true` | succeeds without a prompt (C15) |
| VM identities (C18) | `getent group docker pruefstand`; `stat -c '%a %U' /home/pruefstand /var/lib/pruefstand` | `docker` = `pruefstand` + you only; `700 pruefstand`, `2770 pruefstand` |
| Laptop backup | heartbeat `laptop_backup_age_days` | ≤ 8 |
| Bypass log | `docs/ops/bypass-log.md` | every bypass has a follow-up nightly result |
| Public scheduled workflows active (A12-M11: GitHub disables schedules of a public repo after 60 days without activity) | `gh workflow list -R dheena18/pruefstand --all` | `executor-health.yml`, `ci.yml`, `security.yml`, `live-e2e.yml`, `cassettes.yml`, `deploy.yml` all `active`; re-enable with `gh workflow enable <file>` |
| VM GitHub token scope (N4.4) | on the VM: `gh api repos/dheena18/pruefstand-gate` | `404` (the token sees only the public repo) |
| Gate check pinned (P1.1) | browser: ruleset of `main` → required status `pruefstand/gate` | source = App `pruefstand-bot`; environment `gate-router` deployment branches = `main` only |
| Runner version (A13-M9) | heartbeat `runner_version` vs the latest `actions/runner` release | same or one release behind; GitHub stops assigning jobs to a runner about 30 days behind |
| PAT expiry | GitHub → Settings → Developer settings → fine-grained tokens | > 30 days left |
| GHCR package visibility | `docker logout ghcr.io; docker pull ghcr.io/dheena18/rag-demo@sha256:<recent digest>` on the VM | pulls anonymously (D107) |

## 7. Credential rotation

All secrets with their locations and scopes: `docs/ops/secrets.md` (this table covers the executor's).

| Credential | Where | Rotate | Steps |
| --- | --- | --- | --- |
| `DASHBOARD_DATA_PAT` (fine-grained, `contents: write` on `pruefstand-dashboard-data` only) | private repo secret | ≤ 1 year (expiry set at creation) | create the new token with the same single-repo scope → `gh secret set DASHBOARD_DATA_PAT -R dheena18/pruefstand-gate` → next run pushes a fresh heartbeat → delete the old token |
| `pruefstand-bot` App key | private repo secret `BOT_APP_KEY` **and** public environment secret `gate-router` / `BOT_APP_KEY` (P1.1) | yearly or on suspicion | generate a new key in the App settings → set it in both places (browser, or `gh secret set BOT_APP_KEY -R dheena18/pruefstand-gate` and `gh secret set BOT_APP_KEY --env gate-router -R dheena18/pruefstand` from your laptop) → wait for one `gate-router.yml` run and one executor run to post statuses → delete the old key |
| VM → cluster SSH key | VM `/home/pruefstand/.ssh/id_ed25519_cluster` only (never GitHub, a NAS share, an image or your home) | on suspicion or when the VM is rebuilt | [pruefstand] `ssh-keygen` a new key → `ssh-copy-id` (password typed once, never stored) → `ssh -o BatchMode=yes cairo-s101lp true` → remove the old line from the cluster's `~/.ssh/authorized_keys` → `sudo systemctl restart pruefstand-tunnel` |
| `PRUEFSTAND_CANDIDATE_API_KEY` | `runner.env` of user `pruefstand` (set by the orchestrator per job; your dev stack has its own value in `.env`) | on suspicion | new random value in `.env`; not a security boundary (`gate-net` + `llm-proxy` are) |
| Your VM `gh` token (fine-grained, `dheena18/pruefstand` only, contents + pull requests + workflows write; N4.4, D284) | `gh` config of your user on the VM | ≤ 90 days (expiry set at creation) | create the new token in the browser with the same single-repo scope → `gh auth login --with-token` on the VM → `gh api repos/dheena18/pruefstand-gate` → 404 → delete the old token |
| Runner registration | runner config on the VM | only when moving hosts | persistent runner, registered once (D100); to move: `./config.sh remove`, then register on the new host |
| `age` key pair | your laptop | on loss or suspicion | new key pair → update `AGE_RECIPIENT` in `runner.env` of `pruefstand` → run `backup.yml` once → keep the old private key until all bundles encrypted to it have aged out |

## 8. Baselines storage (no rollover)

Baseline files live in the data root on the VM disk (`$PRUEFSTAND_DATA_ROOT/baselines/`, last 20 per fingerprint, single
writer `baseline-promote.yml`) and in the encrypted weekly backups; the private repo's `baselines`
branch holds only `index.json` (X2.7, ADR-0004), so there is no yearly branch rollover. If the data root
is lost: roll back the TrueNAS snapshot of the VM zvol, or restore the newest bundle (§5, from your laptop) into `$PRUEFSTAND_DATA_ROOT/baselines/`,
or run `baseline-promote.yml` once to re-promote `main`. If the `repo-size` guard ever fails, find the
large blobs (`git rev-list --objects --all | git cat-file --batch-check | sort -k3 -n | tail`) and fix
the writer; never force-push `baselines`.

## 9. Dashboard deploy and optional demo (T8.5 fills in)

**Dashboard.** GitHub Pages (Y7.1, D243) at `https://dheena18.github.io/pruefstand/` (docs at
`…/pruefstand/docs/`), published only by `docs.yml`, whose deploy job runs on `workflow_run` of a
successful `deploy.yml` (dashboard-only: `push: main`, daily cron, `data_sha` dispatch; UI13-06) and takes
that run's `dashboard-site` artefact (N5.2; no dispatch of `docs.yml`); the assembled site must stay ≤ 800 MB
(N5.1). Every Pages build writes `build-id.txt` = `<head_sha>-<deploy_run_id>`; the post-deploy smoke polls
`/pruefstand/build-id.txt` (cache-busting query) until it matches (max 10 min, P5.5), then runs its checks.
The Pages URL is the production URL (read by T9.2). **Rollback, two cases (UI13-08):**

- **data-caused** (the code is fine, the newest data breaks the site): `gh workflow run deploy.yml -R
  dheena18/pruefstand -f data_sha=<last good data SHA>` (from the browser or your laptop); the last good
  `data_sha` is in the `BUILD.json` of the `dashboard-site` behind the newest `docs.yml` run whose
  `post-deploy-smoke` passed;
- **code-caused** (a dashboard regression merged to `main`): open a **revert PR** of the offending commit; it
  goes through the normal checks and its `push: main` run redeploys. A `data_sha` rollback cannot fix this
  case, because it rebuilds today's `main` code.

**Optional demo (Y7.5).** On the VM as [pruefstand]: the demo app containers on the `--internal` network
`demo-net`, `cloudflared` (`10.232.0.2`) on `demo-net` + `demo-egress` (`10.233.0.0/24`; the only one with internet; RFC 1918
dropped for `demo-egress` in `DOCKER-USER`, VM addresses in `PRUEFSTAND-INPUT`, P2.2), `CLOUDFLARE_TUNNEL_TOKEN` in `/home/pruefstand/demo.env`
(mode 600; free Cloudflare account, `[HUMAN]` once). A release becomes demo-ready only through the public
`demo-ready.yml` (`workflow_run` of `release.yml`): its leak probes pass and job `release-demo-ready` uploads
the release asset `demo-ready.json`. The private nightly job `demo-deploy` (`demo-nightly.yml`, then
`demo-e2e`; D244) makes **one** anonymous API call per night (`releases/latest`), downloads `demo-ready.json`
and `image-digests.json` via their `browser_download_url` (no artefact, no token, N5.3, P5.3), and pulls the
public GHCR image by digest; without a `demo-ready.json` it keeps the deployed digest. The e2e test reset runs
inside the container (`docker compose exec rag-demo-e2e curl -X POST localhost:8000/v1/_test/reset`, P5.4).
Your actions, all as a `workflow_dispatch` of `demo-nightly.yml` in the private repo (browser or GitHub mobile
app; inputs `mode` and `tag`; never by editing files under `/var/lib/pruefstand/`):

| Action | Dispatch | Effect |
| --- | --- | --- |
| Deploy now | `mode: deploy` (optional `tag: vX.Y.Z`) | runs the nightly lookup now (for a tag: `releases/tags/<tag>`, still one call) |
| **Pin** (demo rollback) | `mode: pin` | pins the previous deployed digest for 14 days; nightly deploys keep it |
| Unpin | `mode: unpin` | removes the pin; the next run deploys the newest demo-ready release |
| **Kill switch** | `mode: disable` | the public API answers 503 `demo_disabled` at once, no restart |
| Re-enable | `mode: enable` | removes the disable flag |

Changing `DEMO_ENABLED` needs a container restart and is not the kill switch. Token rotation in the
Cloudflare dashboard. No paid provider, so no spending cap is needed.
