# Round 10 resolution — real cluster facts (binding)

Owner-provided facts, 2026-10-31 (from `ollama list`, `nvidia-smi`, `df -h`, `loginctl`):

| Fact | Value |
| --- | --- |
| Cluster host | `cairo-s101lp`, plain SSH, user workdir `/data/dheena` |
| GPUs | 2 × NVIDIA A40, 46 068 MiB each, idle; CUDA 13.4 driver |
| Local disk | `/` 7 GB free (93 % used), `/data` 14 GB free (98 % used) → **no storage or caches on the cluster** |
| NAS | TrueNAS dataset mounted at `/data/dheena/truenas-ollama` (1 PB) |
| Ollama | installed; model `qwen3.8:27b-q8_0` (29 GB) present (verify family/licence/context in T3.1b) |
| Docker / vLLM | not confirmed → assume **not available** on the cluster |
| systemd linger | `Linger=no` → no persistent user services on the cluster |
| Owner direction | execution happens in a **TrueNAS VM** or **WSL**; the cluster is used only for model loading and GPU inference |

## Z1 Topology

| Machine | Runs | Never runs |
| --- | --- | --- |
| **Cluster** `cairo-s101lp` | Two Ollama servers started in `tmux`: `ollama-gpu0` on `:11434` (`CUDA_VISIBLE_DEVICES=0`) and `ollama-gpu1` on `:11435` (`CUDA_VISIBLE_DEVICES=1`), `OLLAMA_MODELS` on the NAS mount | runner, repo checkout, Docker, Qdrant, data, caches, state, locks |
| **TrueNAS VM** `pruefstand-exec` (Ubuntu 24.04, ≥ 8 vCPU, ≥ 32 GB RAM, Docker) | persistent GitHub self-hosted runner (systemd), orchestrator, `gpu.lock` + state files on local VM disk, Qdrant, rag-demo candidate containers, CPU reranker, pruefstand, baselines/backups/datasets on the NAS dataset mounted at `/mnt/pruefstand`, `autossh` tunnels to the cluster | — |
| **WSL2** (owner laptop) | development, tier-1-like local runs, cassette recording | — |

The VM reaches Ollama through `autossh -L 11434:localhost:11434 -L 11435:localhost:11435 cairo-s101lp`.
The SSH private key for the VM→cluster connection lives only on the VM (`~/.ssh`), never in GitHub.

## Z2 File bridge

The cluster and the VM see the same NAS dataset. Layout under the dataset root
(cluster path `/data/dheena/truenas-ollama/`, VM path `/mnt/pruefstand/`):

```text
ollama-models/     OLLAMA_MODELS for both Ollama servers (models pulled once)
bin/               cluster scripts (start/stop/health/switch-mode), written by the VM from the repo
data/  corpus/  datasets/  baselines/  backups/  cache/
```

Cluster scripts are run from the VM: `ssh cairo-s101lp bash /data/dheena/truenas-ollama/bin/<script>.sh`.
Nothing is written to the cluster's `/` or `/data` outside the NAS mount.

## Z3 Models (all served by Ollama; vLLM and TEI dropped from the default plan)

| Role | Model (verify exact tag) | Where | Approx. VRAM |
| --- | --- | --- | --- |
| Tier-2 generator | `qwen3.8:27b-q8_0` (existing), thinking off (`"think": false` / `/no_think`) | GPU0 | ~29 GB + KV |
| Embeddings (tier 2) | `bge-m3` (Ollama) | GPU0 | ~1.5 GB |
| Reranker (tier 2) | `BAAI/bge-reranker-v2-m3` on the **VM CPU** (sentence-transformers), top 20 → top_k | VM | — |
| PR judge | Mistral Small 24B-class, Q4_K_M | GPU1 | ~15 GB |
| Nightly judge | Gemma 27B-class, Q4_K_M (PR judge unloaded at night) | GPU1 | ~17 GB |
| Datagen (weekend) | Llama 70B-class, Q4_K_M, split over both GPUs (all other models unloaded) | GPU0+1 | ~43 GB |
| Tier 1 (GitHub runner) | unchanged: ≤ 2B GGUF on CPU via llama.cpp | GitHub | — |

Ollama settings per server: `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=24h`,
`OLLAMA_FLASH_ATTENTION=1`. Model loads come straight from the NAS (no local cache possible); the
first load per mode is slow and is excluded from timing budgets.

## Z4 Budgets (to be measured in T3.1b, then pinned)

Tier-2 PR (core + robust_pr) ≤ 90 min; nightly ≤ 5 h; datagen as weekend batch. If T3.1b measures more,
the judged metrics in PR runs use a fixed 150-case judged subset of `core` (deterministic metrics stay on
all cases) and SPEC MDE tables are updated.

## Z5 Operations

- Locks and state live on the VM's local disk (single executor), not on the NAS.
- Orchestrator preflight: check both Ollama endpoints through the tunnel; if one is down, run
  `start-ollama.sh` on the cluster over SSH (tmux), wait for health, then continue. A cluster reboot needs no manual step.
- Mode switch (`day` / `night` / `datagen`) = unload/load models through the Ollama API (`keep_alive: 0`), run by the orchestrator under the lock.
- Heartbeat/health/backups (round 8–9) unchanged, but run on the VM.

## Z6 Tasks

- **T0.6** becomes "cluster + NAS facts check" (mostly done by the owner) plus Ollama API checks over a tunnel and a NAS read throughput test.
- **New T0.7 (H+AI) TrueNAS VM setup**: create VM, Docker, mount the NAS dataset at `/mnt/pruefstand`, SSH key + `autossh` tunnels as a systemd service, verify `curl localhost:11434/api/tags` from the VM. T3.1a and T6.2a depend on T0.7.
- **T3.1a**: cluster scripts in `infra/cluster/` (copied to NAS `bin/` by the VM), Ollama dual-server setup, model pulls into `ollama-models/`, mode switching via the Ollama API. No Docker on the cluster.
- **T3.1b**: benchmark through Ollama (German quality, tok/s with `NUM_PARALLEL=4`, VRAM), pin tags, record budgets.
- **T6.2a/b**: runner, orchestrator, Qdrant, candidate containers on the VM; GPU access only via the tunnels.
- Docs: ADR-0005, ci-cd.md, gpu-cluster.md, deployment.md, sequences.md, docker.md, security.md, runbook, SPEC §6, CLAUDE.md map, `.env.example`, `docs/ops/secrets.md`.

## Z7 Owner confirmations (2026-10-31, later the same day)

| Fact | Consequence |
| --- | --- |
| The VM can SSH to the cluster (currently with credentials) and can mount the same NAS dataset | T0.7 switches the VM→cluster login to an SSH key (`ssh-keygen` + `ssh-copy-id`, key only on the VM) so `autossh` and the orchestrator run unattended; password login is never stored anywhere |
| TrueNAS host has 128 GB RAM; the owner gives the **VM 64 GB** | VM sizing: 64 GB RAM. Small models may run on the VM CPU when they fit beside Ubuntu + Qdrant + Docker (budget ≤ 24 GB for CPU models): the reranker, the tier-1 ≤ 2B GGUF for local reproduction of tier-1 runs, and the CPU embedding model. GPU models stay on the cluster. |
| Daily work happens in **VS Code on Windows**, with the terminal connected to the VM via Remote-SSH | The VM is the primary development + execution machine (the coding agent runs its commands on the VM through VS Code Remote-SSH). WSL2 becomes optional. T0.0 bootstrap targets the VM (Ubuntu 24.04) first; WSL steps stay as an alternative. |
| Ollama loads models from the NAS only if its start command sets the model directory | `infra/cluster/start-ollama.sh` exports `OLLAMA_MODELS=/data/dheena/truenas-ollama/ollama-models` (and `OLLAMA_HOST=127.0.0.1:<port>`, `CUDA_VISIBLE_DEVICES=<gpu>`) before `ollama serve`, for each of the two servers. The existing `qwen3.8:27b-q8_0` is moved/re-pulled into that directory once (T3.1a). |

New variables (VM `.env` unless noted): `CLUSTER_SSH_HOST=cairo-s101lp`, `CLUSTER_NAS_ROOT=/data/dheena/truenas-ollama`,
`PRUEFSTAND_DATA_ROOT=/mnt/pruefstand`, `OLLAMA_GPU0_URL=http://localhost:11434`, `OLLAMA_GPU1_URL=http://localhost:11435`.
`PRUEFSTAND_MODEL_CACHE` is dropped.
