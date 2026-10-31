# Setup log — what was actually done on the real machines

This is a record of the setup steps already done by the owner, with the exact commands. It holds **no
credentials**: user names, host names and ports of the cluster's public SSH endpoint are written as
placeholders. Fill them in only on the VM, in `/home/pruefstand/.ssh/config` (never in git, never in `.env`).

| Placeholder | Meaning |
| --- | --- |
| `<cluster-user>` | login user on the A40 cluster |
| `<cluster-ssh-host>` | public SSH endpoint of the cluster (a TCP tunnel service in front of the cluster's sshd) |
| `<cluster-ssh-port>` | port of that endpoint |

Machines: **VM** = Ubuntu VM `pruefstand-exec` on TrueNAS (where these commands run unless marked),
**cluster** = `cairo-s101lp` with 2 × A40 and Ollama.

## 1. Cluster facts collected (2026-10-31)

```bash
# on the cluster
ollama list
nvidia-smi
df -h
loginctl show-user $USER -p Linger
```

Results: 2 × NVIDIA A40 (46 068 MiB each); local disk nearly full (`/` 7 GB free, `/data` 14 GB free);
NAS mounted at `/data/dheena/truenas-ollama`; `Linger=no`; **one** Ollama server using both GPUs.

## 2. VM → cluster SSH with a key (no password stored)

```bash
# VM: service user that owns the cluster connection
sudo adduser --system --group --home /home/pruefstand --shell /bin/bash pruefstand

# VM: key without passphrase (needed for an unattended tunnel)
sudo -u pruefstand ssh-keygen -t ed25519 -N "" -f /home/pruefstand/.ssh/id_ed25519_cluster -C "pruefstand-exec to cluster"

# VM: install the key on the cluster (the cluster password is typed once here and not stored)
#     note: ssh / ssh-copy-id take the port with -p, not host:port
sudo -u pruefstand ssh-copy-id -i /home/pruefstand/.ssh/id_ed25519_cluster.pub -p <cluster-ssh-port> <cluster-user>@<cluster-ssh-host>

# VM: host alias, so nothing else ever needs the address
sudo -u pruefstand tee /home/pruefstand/.ssh/config > /dev/null <<'EOF'
Host cairo-s101lp
    HostName <cluster-ssh-host>
    Port <cluster-ssh-port>
    User <cluster-user>
    IdentityFile ~/.ssh/id_ed25519_cluster
    IdentitiesOnly yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ExitOnForwardFailure yes
EOF
sudo chmod 600 /home/pruefstand/.ssh/config
```

### Problem met: key offered but password still asked

```bash
# VM: see which keys are offered and which methods the server accepts
sudo -u pruefstand ssh -v cairo-s101lp true 2>&1 | grep -iE "identity file|offering|authentications that can continue|server accepts|no more"

# cluster: permissions check
ls -ld ~ ~/.ssh ~/.ssh/authorized_keys; grep -c "pruefstand-exec" ~/.ssh/authorized_keys
```

Cause: the cluster home folder was group-writable (`drwxrwx---`), so sshd ignored `authorized_keys`.
Fix, on the cluster (works from any folder; `~` is the home folder):

```bash
chmod g-w ~
ls -ld ~          # now drwxr-x---
```

Test (VM, no password prompt):

```bash
sudo -u pruefstand ssh cairo-s101lp 'nvidia-smi --query-gpu=name,memory.total --format=csv'
# NVIDIA A40, 46068 MiB  (twice)
```

## 3. Permanent SSH tunnel to the cluster's Ollama

```bash
# VM: where does Ollama listen on the cluster?
sudo -u pruefstand ssh cairo-s101lp 'ss -ltnp 2>/dev/null | grep -i ollama || ss -ltn | grep 11434'
# LISTEN ... 127.0.0.1:11434 ... ("ollama",...)

# VM: autossh + systemd unit
sudo apt install -y autossh
sudo tee /etc/systemd/system/pruefstand-tunnel.service > /dev/null <<'EOF'
[Unit]
Description=Pruefstand SSH tunnel to cluster Ollama
After=network-online.target
Wants=network-online.target

[Service]
User=pruefstand
Environment=AUTOSSH_GATETIME=0
ExecStart=/usr/bin/autossh -M 0 -N -L 127.0.0.1:11434:localhost:11434 cairo-s101lp
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now pruefstand-tunnel

# VM: checks
systemctl status pruefstand-tunnel --no-pager | head -5
curl -s http://127.0.0.1:11434/api/tags
```

Result of `/api/tags` (2026-10-31):

| Field | Value |
| --- | --- |
| model | `qwen3.8:27b-q8_0` |
| family (Ollama) | `qwen35` |
| parameters | 27.3 B |
| quantisation | Q8_0 |
| size | 29 978 242 050 bytes |
| digest | `8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039` |
| native context length | 262 144 |
| capabilities | completion, tools, thinking, vision |

T0.7 later adds a second forward on the same line for Docker containers:
`-L 172.17.0.1:11434:localhost:11434` (needs Docker installed so `docker0` exists).

## 4. VM `.env` entries from this setup

```
CLUSTER_SSH_HOST=cairo-s101lp
OLLAMA_GPU0_URL=http://127.0.0.1:11434
OLLAMA_GPU1_URL=http://127.0.0.1:11434
```

Both URLs point to the same single Ollama server (see ADR-0018).

## 5. Not used: public ngrok URL for Ollama

An ngrok URL that exposes the cluster's Ollama exists. It is **not** used by Prüfstand: Ollama has no
authentication, so a public URL lets anyone use the GPUs and call `/api/delete` / `/api/pull`. Free ngrok
plans also limit requests and bandwidth. The SSH tunnel above replaces it. If ngrok stays running for
other purposes, protect it (basic auth or IP allow-list in its traffic policy) and rotate the URL.

## 6. VM data folder (`PRUEFSTAND_DATA_ROOT`) — on the VM's own disk

The VM's system disk is a 500 GB zvol on the TrueNAS pool (`df -h /` → 491 G, 450 G free), so the data
folder is a plain directory on it. No network mount.

```bash
# VM
df -h /
sudo mkdir -p /mnt/pruefstand/{data,corpus,datasets,baselines,backups,cache,logs}
sudo chown -R pruefstand:pruefstand /mnt/pruefstand
sudo chmod -R 2775 /mnt/pruefstand
sudo usermod -aG pruefstand $USER            # takes effect at the next login
sudo -u pruefstand touch /mnt/pruefstand/cache/.t && sudo -u pruefstand rm /mnt/pruefstand/cache/.t && echo "write ok"
```

VM `.env`: `PRUEFSTAND_DATA_ROOT=/mnt/pruefstand`.

Backups: TrueNAS **Data Protection → Periodic Snapshot Tasks** on the VM's zvol (daily, keep 14 days), plus
the planned weekly encrypted copy to the owner's laptop.

### Tried and dropped: NFS share from TrueNAS to the VM

A separate dataset `SSD/pruefstand` with an NFS share was created and the VM was set to mount it. The VM could
not reach its own TrueNAS host (`ping` → "Destination Host Unreachable"): the VM's NIC is attached directly to
the physical NIC, and such a VM cannot talk to its host. The fix would be a bridge (`br0`) in TrueNAS
networking; it did not work on the first try, and the VM disk is large enough, so NFS was dropped.

```bash
# commands used, kept for reference (TrueNAS shell; truenas_admin needs sudo for chown)
cd /mnt/SDD/SSD/pruefstand && sudo chown -R <pruefstand-uid>:<pruefstand-gid> . && sudo chmod -R 2775 .
# VM: the fstab line was removed again
sudo sed -i '\#<truenas-ip>:/mnt/SDD/SSD/pruefstand#d' /etc/fstab && sudo systemctl daemon-reload
```

The unused dataset `SSD/pruefstand` and its NFS share can be deleted in TrueNAS.

## 7. Cluster Ollama: settings and model storage

### Start script on the cluster (owner's `~/start-ollama.sh`)

```bash
#!/usr/bin/env bash
set -e
export OLLAMA_HOST=127.0.0.1:11434          # only reachable through the SSH tunnel
export CUDA_VISIBLE_DEVICES=0,1             # one server, both A40s (ADR-0018)
export OLLAMA_CONTEXT_LENGTH=8192           # safe default; Prüfstand always sends num_ctx itself
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0            # half-size KV cache
export OLLAMA_KEEP_ALIVE=24h                # models stay loaded
export OLLAMA_NUM_PARALLEL=4                # 4 parallel requests per model
export OLLAMA_MAX_LOADED_MODELS=3           # generator + embeddings + judge
export OLLAMA_NOPRUNE=1                     # never auto-delete model files
export PATH="$HOME/ollama-local/bin:$PATH"
export LD_LIBRARY_PATH="$HOME/ollama-local/lib:$LD_LIBRARY_PATH"
export OLLAMA_MODELS="/data/dheena/Models"  # cluster's own disk (ADR-0019)
exec "$HOME/ollama-local/bin/ollama" serve
```

Start / restart (detached, survives logout):

```bash
# cluster
pkill -x ollama; sleep 3
setsid nohup ~/start-ollama.sh > /data/dheena/ollama.log 2>&1 < /dev/null &
sleep 5; tail -5 /data/dheena/ollama.log
```

Check from the VM:

```bash
time curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen3.8:27b-q8_0","prompt":"Sag Hallo.","think":false,"stream":false,"options":{"num_ctx":8192}}' | head -c 300; echo
curl -s http://127.0.0.1:11434/api/ps
```

Result (2026-10-31, model already loaded): German answer "Hallo! Wie kann ich dir heute helfen?" in **1.0 s**.

### Tried and dropped: loading models from the NAS (rclone WebDAV mount)

The NAS dataset `/mnt/SDD/SSD/Ollama` (subfolder `models`) is mounted read-only on the cluster at
`/data/dheena/truenas-ollama` with rclone. Setting `OLLAMA_MODELS` to it worked, but the link between the
cluster and the NAS gave **~6 MB/s** (≈ 80 min for the 29 GB generator, after every Ollama restart). Models
therefore stay on the cluster's own disk (ADR-0019).

```bash
# cluster: how fast is the network while a model loads?
IF=$(ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}'); a=$(cat /sys/class/net/$IF/statistics/rx_bytes); sleep 10; b=$(cat /sys/class/net/$IF/statistics/rx_bytes); echo "$IF: $(( (b-a)/10/1024/1024 )) MB/s"

# cluster: the rclone mount (kept, not used by Ollama); options that are valid with rclone 1.63.1
/home/<cluster-user>/bin/rclone mount nas: /data/dheena/truenas-ollama --read-only --vfs-cache-mode off \
  --buffer-size 256M --vfs-read-chunk-size 64M --vfs-read-chunk-size-limit 1G --dir-cache-time 1h \
  --attr-timeout 1h --timeout 10m --contimeout 60s --retries 5 --low-level-retries 20 \
  --daemon --log-file /data/dheena/rclone
# remounting needs Ollama stopped and no shell inside the folder, else "Device or resource busy":
#   pkill -x ollama; cd ~; fuser -vm /data/dheena/truenas-ollama; fusermount3 -u /data/dheena/truenas-ollama
```

Note: the NAS folder `/mnt/SDD/SSD/Ollama` also contained an SSH private key (`id_ed25519`); it should be
moved out of the share (and replaced if it was ever exposed).

### Adding or swapping a model (disk is small: ~14 GB free next to the generator)

```bash
# cluster
df -h /data                                   # check space first; keep ≥ 2 GB free
ollama list
ollama rm <model-tag>                         # free space if needed (never the generator)
ollama pull <model-tag>
```

## 8. Notes

- If the cluster's public SSH endpoint gets a new port, change only `Port` in `/home/pruefstand/.ssh/config`
  and run `sudo systemctl restart pruefstand-tunnel`.
- The cluster's sshd is reachable from the internet through that endpoint: keep a strong password on the
  cluster account or ask the admin for key-only login.
