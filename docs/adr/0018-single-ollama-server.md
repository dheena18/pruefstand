# 0018 — One Ollama server on the cluster for both A40s

- Status: Accepted (amended by [ADR-0019](0019-local-model-storage-small-disk.md), 2026-10-31: model dir on the
  cluster disk, `OLLAMA_KV_CACHE_TYPE=q8_0`, the owner's `~/start-ollama.sh` as start script, one judge, no datagen mode)
- Date: 2026-10-31
- Tasks: T0.6, T0.7, T3.1a, T3.1b, T5.1, T5.2a, T6.2a, T6.2b
- Supersedes: the two-server part of D196, D198 (server env), D203 (`OLLAMA_GPU1_URL` value), D206/D242/D285
  (second-port forwards and firewall rules), D207 and D270 (per-server wording), D279 (per-server template
  keys); the per-GPU server mentions in ADR-0005/0009/0010

## Context

Rounds 10–13 planned one Ollama server per GPU on `cairo-s101lp`: GPU0 on `127.0.0.1:11434`
(`CUDA_VISIBLE_DEVICES=0`, generator + `bge-m3`) and GPU1 on the next port (`CUDA_VISIBLE_DEVICES=1`, PR judge
or nightly judge), plus a third server over both cards for datagen (D196, D198). The
owner checked the real machines on 2026-10-31 (`docs/ops/setup-log.md`):

- the cluster already runs **one** Ollama server (`127.0.0.1:11434`, process owned by the cluster user)
  that sees **both** A40s;
- the VM already reaches it through `pruefstand-tunnel.service` (autossh, host alias `cairo-s101lp` in
  `/home/pruefstand/.ssh/config`; the alias uses a non-default SSH `Port` on a public TCP endpoint);
- `/api/tags` lists `qwen3.8:27b-q8_0`: Ollama family `qwen35`, 27.3 B, `Q8_0`, digest
  `8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039`, native context 262 144, capabilities
  `completion, tools, thinking, vision`;
- a public ngrok URL that exposes this Ollama exists (no authentication).

A second server on its own port would mean a second process the owner does not run today, a second port in
the tunnel and firewall, a shared model store with two writers, and a datagen restart into a third
server. Ollama's own scheduler already places each model on a GPU and splits a model across both cards
only when it does not fit on one.

## Decision

1. **One Ollama server** on the cluster serves both GPUs: `CUDA_VISIBLE_DEVICES=0,1`,
   `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_NUM_PARALLEL=4`,
   `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_MODELS=$CLUSTER_DATA_ROOT/Models` on the cluster's own disk (ADR-0019; the NAS
   path is rejected), plus `OLLAMA_NOPRUNE=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (ADR-0019; was `f16`),
   `OLLAMA_CONTEXT_LENGTH=8192` (default only), `OLLAMA_FLASH_ATTENTION=1`. There is no second port, no per-GPU server,
   no datagen server and no `OLLAMA_SCHED_SPREAD`.
2. **Settings stay two names.** `OLLAMA_GPU0_URL` and `OLLAMA_GPU1_URL` remain separate settings (code and
   `endpoints.yaml` unchanged); on the VM both are `http://127.0.0.1:11434`. They name logical lanes
   (generator lane, judge lane), not ports or cards, so a later split onto two servers or hosts is a
   `.env` change only.
3. **GPU placement is Ollama's.** No script pins a model to a card. `health.sh` checks through `/api/ps`
   that every resident model is fully in VRAM (`size_vram == size`, else the existing exit **15**) and
   reports which GPU holds it (`status.sh`: `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory`
   joined with the Ollama runner process of each model; **verify** the join on the pinned version in
   T3.1a). A model spread over both cards is also exit 15 (there is no `datagen` mode since ADR-0019).
4. **Generator/judge separation is logical**, by model, not by port: `llm-proxy` lets candidates call
   only the run's catalogue generator and embedding tags (403 for any judge tag, `/api/generate`,
   `/api/ps`, `/api/pull`, …) and strips `keep_alive`, so a candidate cannot load, unload or query a
   judge.
5. **Cluster scripts (T3.1a)** reuse the running server when it is healthy (`/api/tags` answers on
   `127.0.0.1:11434`); only if none runs does `start-ollama.sh` start **one** server with `setsid nohup`
   through the owner's `~/start-ollama.sh` (ADR-0019). Nothing ever starts a second server. Mode switches (`day`, `night`)
   only load and unload models through the API (`keep_alive: 0` to unload); no server restart, no
   per-GPU server. A running server whose environment differs from `cluster.env` (read from
   `/proc/<pid>/environ`) is reported as WARN; restarting it is an owner step (runbook).
6. **Generator model.** The catalogue entry is the existing `qwen3.8:27b-q8_0`, pinned to digest
   `8f5fb6b7…1766039`, Ollama family `qwen35` mapped to the plan family `qwen` in
   `core/data/model_families.yaml`; capability `thinking` is present, so `"think": false` is required on
   every request (D95).
7. **Tunnel** forwards only `11434`: `127.0.0.1:11434` now (done, setup log §3) and
   `172.17.0.1:11434` once Docker exists (T0.7). The VM firewall rules name only `11434`.
8. **No public exposure.** The ngrok URL is not used and is recorded as a rejected option in
   `security.md` (no authentication on Ollama).

## Consequences

- Fewer moving parts: one process, one port, one log and pid file, one forward per bind address.
- `MAX_LOADED_MODELS=3` fits every mode: day = night = generator + `bge-m3` + the one judge `gemma3:12b`
  (ADR-0019); embedding swap = generator + e5 + judge. A fourth model would evict one, which the run counts as `model_reload`.
- Placement is not guaranteed: two models could land on one card. `health.sh` makes that visible; the
  memory plan (gpu-cluster.md §3) means the generator (≈ 35 GB with KV) and the judge do not fit one card
  together, so Ollama puts them on different cards. The overlap of nightly generation and judging still
  holds.
- `OLLAMA_NUM_PARALLEL` is server-wide, so "lower parallel to 2 for the judge" (D270/D306) lowers it for
  every model; T3.1b records the effect on the generator budget.
- The existing server may be shared with the cluster user's other work; the GPU lock on the VM does not
  cover such use. `/api/ps` showing a model outside the mode is unloaded by `--repair` only if it is in
  the catalogue; any other resident model is reported (WARN) and left alone.
- The ngrok endpoint, if still running, is outside this design; the setup log asks the owner to protect or
  stop it.
