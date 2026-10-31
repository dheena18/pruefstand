# `infra/vm` — the VM `pruefstand-exec` (T0.7)

One Ubuntu VM on the TrueNAS host is both the owner's development machine (VS Code Remote-SSH, coding agents) and
the future gate executor. This folder holds everything that is installed **on the VM**: the service user, the GPU
lock, the data root, the cluster SSH identity, the tunnel to the cluster's Ollama, the Docker egress networks with
their firewall rules, and `vm_check.sh`. Decisions: round 11 Y1 (one service identity), D211–D213, D242, ADR-0018
(one Ollama server, port 11434 only), ADR-0019 (plain data directory on the VM disk, no mount). What was already done
by hand on 2026-10-31 is in `docs/ops/setup-log.md`; the scripts here *codify and verify* it and never overwrite it.

Every command below names **the user it runs as** and **the machine**. `VM` = `pruefstand-exec`; `owner` = the
owner's normal login user on the VM; `pruefstand` = the system user that owns the executor side.

## VM spec

| Item | Value |
| --- | --- |
| Hypervisor | TrueNAS (host 128 GB RAM); the VM autostarts with the host (boot order recorded in `docs/decisions.md`) |
| OS | Ubuntu Server; **26.04.1** on the real VM (the prompts assume 24.04; `vm_check os` accepts 24.04 and later, 26.04 as WARN) |
| Size | 64 GB RAM, >= 8 vCPU, 500 GB system disk (a zvol on the TrueNAS pool) |
| Docker | **rootful**, Ubuntu packages `docker.io` + `docker-compose-v2` (no `docker-ce` candidate for 26.04) |
| Backups | TrueNAS **Periodic Snapshot Task** on the VM zvol (daily, keep 14) + the weekly encrypted laptop copy (T6.2b) |

## Identities (Y1)

| Who | Is | Owns / may do |
| --- | --- | --- |
| `pruefstand` (system user + group, home `/home/pruefstand` mode 0700) | the executor identity | cluster key `/home/pruefstand/.ssh/id_ed25519_cluster`, `pruefstand-tunnel.service`, executor state and secrets (T6.2a), `/var/lib/pruefstand` |
| owner (login user; groups `pruefstand` + `docker`) | the developer; coding agents run as this user | `pruefstand-lock <cmd>` for GPU work, cluster commands only through `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster <op>` (T3.1a); never touches `/var/lib/pruefstand/**` or `/home/pruefstand/**` by hand |
| group `docker` | exactly `pruefstand` + the owner | rootful Docker; the owner and agents are therefore root-equivalent on this dedicated VM (accepted, `security.md` C18) |

The owner never holds a copy of the cluster key. A third member of group `docker` is a `vm_check docker-group` FAIL.

## Files

| File | Runs as | Purpose |
| --- | --- | --- |
| `setup-users.sh` | root (`sudo`) | user/group, owner membership, group `docker`, `/var/lib/pruefstand` (2770), `gpu.lock` (0660), installs `pruefstand-lock` |
| `pruefstand-lock` | owner / any | `flock -w ${GPU_LOCK_TIMEOUT_S:-7200} /var/lib/pruefstand/gpu.lock env PRUEFSTAND_LOCK_HELD=1 "$@"`; exit 75 `gpu.lock busy` |
| `setup-data-root.sh` | root | `/mnt/pruefstand` + `data corpus datasets baselines backups cache logs` (2775, `pruefstand:pruefstand`) + sentinel `.pruefstand-data-root` |
| `setup-ssh-key.sh` | `pruefstand` | verifies/creates the key and the `Host cairo-s101lp` block; BatchMode test |
| `pruefstand-tunnel.service`, `install-tunnel.sh` | root | the system unit (forwards on `127.0.0.1` and `172.17.0.1`) and its installer |
| `setup-proxy-net.sh` | root | networks `proxy-egress` (10.231.0.0/24) and `demo-egress` (10.233.0.0/24), installs the firewall script and unit |
| `pruefstand-firewall.sh`, `pruefstand-firewall.service` | root (via systemd) | rules in `DOCKER-USER` and the own chain `PRUEFSTAND-INPUT` |
| `vm_check.sh` | owner | `CHECK <id> <PASS\|FAIL\|WARN> <detail>` lines for V1–V7 |

All scripts are idempotent, take `--dry-run` where they change the system (it prints `PLAN ...` lines), contain no
secret and no `systemctl --user`. `vm-check-<date>.out` is real output saved after the reboots (S7).

## The lock and `MAINTENANCE`

`/var/lib/pruefstand/gpu.lock` is the **one** GPU lock of the host. The orchestrator takes it once per job; the owner
and agents take it through `pruefstand-lock`, so dev GPU work and gate jobs exclude each other:

```bash
# owner, VM
pruefstand-lock make test-gpu
pruefstand-lock true; echo $?            # 0 when free, 75 "gpu.lock busy" after GPU_LOCK_TIMEOUT_S
```

`/var/lib/pruefstand/MAINTENANCE` is a **file**, never an environment variable (Y1.2). Set it only for a model swap
(ADR-0019): `touch /var/lib/pruefstand/MAINTENANCE` as the owner; clear it with `rm` when done. `vm_check lock-dir`
reports it as WARN "maintenance set". No script here creates or removes it.

## Data root (ADR-0019)

`/mnt/pruefstand` is a **plain directory** on the VM's own disk (500 GB zvol): no NFS share, no mount unit, no
`/etc/fstab` line, so nothing in boot depends on storage. The executor preflight needs it to exist, be writable by
`pruefstand` and have >= 20 GB free; otherwise the job ends with `infra_error="data_root_unavailable"` (T6.2a).
Snapshots of the zvol are the backup. `vm_check data-root` and `data-root-rw` verify it.

## Cluster key and tunnel

The key `id_ed25519_cluster` belongs to `pruefstand` and never leaves `/home/pruefstand`. The unit
`pruefstand-tunnel.service` (system unit, `User=pruefstand`) runs
`autossh -M 0 -N -o ExitOnForwardFailure=yes -L 127.0.0.1:11434:localhost:11434 -L 172.17.0.1:11434:localhost:11434 cairo-s101lp`
after `network-online.target` and `docker.service` (`docker0` must exist for the second forward). Only port 11434 is
forwarded (ADR-0018, one Ollama server for both GPUs). No public URL to the cluster's Ollama is used anywhere.
If the cluster's SSH port changes, edit only `Port` in `/home/pruefstand/.ssh/config` (as `pruefstand`) and
`sudo systemctl restart pruefstand-tunnel`.

### Rotate the key

```bash
# 1. pruefstand, VM: move the old key away and make a new one (setup-ssh-key.sh creates it when missing)
sudo -u pruefstand mv /home/pruefstand/.ssh/id_ed25519_cluster /home/pruefstand/.ssh/id_ed25519_cluster.old
sudo -u pruefstand mv /home/pruefstand/.ssh/id_ed25519_cluster.pub /home/pruefstand/.ssh/id_ed25519_cluster.pub.old
sudo -u pruefstand bash -s -- --no-verify < infra/vm/setup-ssh-key.sh      # prints the ssh-copy-id line
# 2. pruefstand, VM: install the new public key on the cluster (use the old key for this one login)
sudo -u pruefstand ssh-copy-id -i /home/pruefstand/.ssh/id_ed25519_cluster.pub -o IdentityFile=/home/pruefstand/.ssh/id_ed25519_cluster.old -p <port> <user>@<host>
# 3. cluster, owner's cluster account: delete the old line from ~/.ssh/authorized_keys (comment "pruefstand-exec to cluster")
# 4. pruefstand, VM: remove the old key files, then restart the tunnel
sudo -u pruefstand rm /home/pruefstand/.ssh/id_ed25519_cluster.old /home/pruefstand/.ssh/id_ed25519_cluster.pub.old
sudo systemctl restart pruefstand-tunnel
```

## How `llm-proxy` reaches the tunnel (D242)

Candidates are only on the internal network `gate-net` and call `http://llm-proxy:11500`. `llm-proxy` (T6.2a) is on
`gate-net` **and** the small non-internal bridge `proxy-egress` (10.231.0.0/24, created by `setup-proxy-net.sh`) and
reaches Ollama at `172.17.0.1:11434`, the tunnel's second listener. `pruefstand-firewall.sh` accepts TCP 11434 to
`172.17.0.1` only from 10.231.0.0/24 and drops it from everything else, in **both** `DOCKER-USER` and `PRUEFSTAND-INPUT`
(container -> host traffic is delivered locally and passes `INPUT`, not `FORWARD`). The demo networks (R13 P2.2):
`demo-net` 10.232.0.0/24 is `--internal`; `demo-egress` 10.233.0.0/24 (cloudflared's internet side) may not reach
RFC 1918 addresses, and neither demo network may reach a VM address. The rules live in `pruefstand-firewall.service`
(a oneshot with `PartOf=docker.service`, so they are re-applied whenever Docker restarts). The script touches only its
own chain and rules; it never flushes the ruleset or enables the distro nftables unit (that would delete Docker's
NAT and isolation rules).

## Ports (Y1.4)

The executor stack uses the default host ports. The owner/agent **dev** stack uses compose profile `dev` with
`PORT_OFFSET=10000` (Qdrant 16333/16334, rerank 18201, rag-demo 18000; `make up PROFILES="core live dev"`). Nothing in
this folder publishes a port; SSH is the only inbound port from the LAN.

## Checks

```bash
# owner, VM (run `sudo -v` first: the iptables checks and the checks "as pruefstand" use sudo -n)
infra/vm/vm_check.sh                       # all checks, exit 1 on any FAIL
infra/vm/vm_check.sh firewall tunnel       # selected ids
infra/vm/vm_check.sh --confirm vscode      # record an owner-confirmed check (tunnel-reboot | host-reboot | vscode)
infra/vm/vm_check.sh --restart-drill       # N4.2: restarts Docker ONCE; refuses (exit 75) while gpu.lock is held
```

`vm_check.sh` never restarts Docker. The probe image is `curlimages/curl:8.11.1`; pin it by digest for the Done-when
run: `PROBE_IMAGE=curlimages/curl@sha256:<digest> infra/vm/vm_check.sh firewall`. The demo probes use `TRUENAS_HOST_IP`
(the TrueNAS host's LAN address, never committed) when set.

## Recovery

| Event | What happens | What to do |
| --- | --- | --- |
| VM reboot | `docker.service`, `pruefstand-firewall.service` and `pruefstand-tunnel.service` start by themselves | `infra/vm/vm_check.sh`; if the tunnel is down: `sudo systemctl restart pruefstand-tunnel` |
| TrueNAS host reboot (Y5.3) | the VM autostarts; no unit depends on storage | the same check, then `vm_check.sh --confirm host-reboot`; if the VM did not start, start it in the TrueNAS UI and fix the autostart order |
| Docker restarted | the firewall oneshot is restarted with it (`PartOf=`) | `vm_check.sh firewall`; manual repair: `sudo systemctl restart pruefstand-firewall` |
| Cluster reboot | Ollama is gone; the tunnel reconnects by itself | on the cluster start Ollama with the owner's `~/start-ollama.sh` (setup log section 7); then `curl -s 127.0.0.1:11434/api/tags` on the VM |
| Cluster SSH port changed | the tunnel keeps failing | edit `Port` as described above, restart the tunnel |
| Data root unusable | jobs end with `infra_error="data_root_unavailable"` | check `vm_check.sh data-root data-root-rw`; fix ownership with `sudo infra/vm/setup-data-root.sh` |

## First-time install order (S2b–S7)

The exact commands, user and machine for each step are in the T0.7 pull request and mirror the table above. Order:
`setup-users.sh`, `setup-data-root.sh` (verifies the existing directory), `setup-ssh-key.sh` (verifies), `install-tunnel.sh`,
`setup-proxy-net.sh`, `vm_check.sh`, reboot the VM, `vm_check.sh`, reboot the TrueNAS host, `vm_check.sh`, save the output as
`infra/vm/vm-check-<date>.out` and fill rows V1–V7 of `docs/engineering/gpu-cluster.md` section 0.2.
