# infra/gpu: GPU serving from the VM (T3.1a)

One Ollama server on the cluster `cairo-s101lp` serves both A40s (ADR-0018); the models live on the cluster's own
disk, `<models-dir>` (ADR-0019). Everything in this directory runs **on the VM** `pruefstand-exec`; the scripts in
`infra/cluster/` run on the cluster and are copied there over SSH. Numbers (VRAM, budgets) live in
`docs/engineering/gpu-cluster.md`; names and exit codes in `docs/architecture/interfaces.md` section 1.5.

| File | What it is |
| --- | --- |
| `models.yaml`, `endpoints.yaml` | the catalogue (digests, per-model `options`, bounds) and the service map; checked by `catalogue_schema.py` |
| `switch-mode.sh day\|night [--dry-run]` | API loads/unloads only: the server holds exactly generator, `bge-m3`, judge `gemma3:12b` (same set in both modes) |
| `health.sh [--repair] [--mode day\|night]` | CSV `check,status,detail` and the exit codes below; `--repair` starts the server only if none answers, then normalises the model set |
| `fetch-model.sh <id> \| --rm <id>` | pull a catalogue model (digest checked) or remove a non-generator one under `MAINTENANCE` |
| `unload-all.sh` | unload every catalogue model; the server keeps running (`make gpu-down`) |
| `deploy-cluster-bin.sh [--check] [--bin-dev] [--print-sums]` | copy `infra/cluster/*.sh` + the rendered `cluster.env` over SSH, write `SHA256SUMS` |
| `pruefstand-cluster`, `install-cluster-wrapper.sh`, `lib/cluster_ssh.sh` | the only way to reach the cluster as the owner; fixed ops, lock proof for the mutating ones |
| `rerank/`, `compose.gpu.yml` | `rerank-cpu` (TEI-compatible `POST /rerank`, no auth) for compose profile `gpu` |
| `lib/gpu_common.sh`, `gpu_catalogue.py`, `gpu_health.py` | shared helpers; JSON bodies and checks come from Python, never from shell string building |

## Rules every script follows

- `switch-mode.sh`, `health.sh`, `fetch-model.sh`, `unload-all.sh` never take the GPU lock; run them with
  `pruefstand-lock <cmd>` (the `make gpu-*` targets do) or they exit 2 "run under the GPU lock".
- Native Ollama API only (`/api/generate`, `/api/ps`, `/api/tags`), never `/v1/*`. A load sends exactly
  `{model, keep_alive, options: <catalogue options>}`, so the first real request does not reload the model.
- Nothing creates or removes `/var/lib/pruefstand/MAINTENANCE`. No mode starts, stops or restarts the server.
- **Disk rule:** `fetch-model.sh` reads the free space of the models disk right before every pull; below model size + the
  2 GB reserve it stops with **exit 17** and asks the owner. It never starts the pull in that case.
- Cluster calls go through `lib/cluster_ssh.sh` only: plain ssh as `pruefstand`, `sudo -n -u pruefstand
  /usr/local/bin/pruefstand-cluster <op>` as anyone else.

## `health.sh` exit codes

`0` ok (WARN rows do not fail) | `10` free VRAM below `PRUEFSTAND_MIN_FREE_VRAM_MIB` (1024) on a card | `11` an endpoint
or a mode model is not answering/resident, or a second `ollama serve` | `12` `status.sh` unreachable over ssh | `13` a
resident digest differs from the catalogue | `14` the cluster bin dir differs from this checkout (`make gpu-deploy-bin`)
| `15` a model not fully in VRAM or spread over both cards | `16` data root missing, not writable or under 20 GB free |
`2` not under the lock | `64` usage. When several apply, the first of 16, 11, 12, 14, 13, 15, 10 is returned.
`fetch-model.sh`: `0`, `1` pull/digest failure, `2`, `3` `--rm` without `MAINTENANCE`, `17` not enough free disk
space (ask the owner), `64`.

## Recovery

- Server down: `make gpu-repair` (starts the owner's `~/start-ollama.sh` detached through `start-ollama.sh`, only if no
  server answers; waits up to `REPAIR_WAIT_S` = 300 s; then loads the day set).
- Cluster scripts out of date or edited (exit 14): `make gpu-deploy-bin`, then `make gpu-health`.
- A killed job left an e5 or RQ2 model loaded: `make gpu-repair` unloads catalogue models outside the mode first.
- Disk full (exit 17): free space on the cluster disk (swap rule, `docs/engineering/gpu-cluster.md` section 8), then
  `make gpu-pull ID=...` again.

## Owner actions for T3.1a (nothing here can be done by a coding agent: sudo, the GPU, the real lock)

Run on the VM `pruefstand-exec` as the owner login user from a checkout of the merged `main`, in this order.

1. **Install the wrapper** (sudo): `sudo infra/gpu/install-cluster-wrapper.sh`. It checks the sudoers file with
   `visudo -c` before installing. Check: `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status` prints a CSV.
2. **Deploy the cluster scripts** (needs sudo; no lock): `make gpu-deploy-bin`, then
   `make gpu-deploy-bin DEPLOY_ARGS=--check` (exit 0 = deployed set equals this checkout).
3. **S2b [GPU][HUMAN] pull the ADR-0019 set** (each pull is refused with exit 17 if the disk is too full):
   `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status | grep disk-models` (before), then
   `make gpu-pull ID=ollama/bge-m3` and `make gpu-pull ID=ollama/gemma3:12b`, then the status line again (after).
   Paste both lines, the two digests and whether `status.sh` reported `env` WARN rows.
4. **S8 [GPU][HUMAN] bring-up:** `make gpu-up && make test-gpu-locked`; then `make gpu-night-up`, then `make gpu-up`.
   After each: `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status` and `make gpu-health` (paste the CSV).
   Also record the first-load time of each model and `kv_bytes_per_token` (from `ollama.log`) for `models.yaml`.
5. **Logout test [GPU][HUMAN]:** log out of every SSH session, wait 5 minutes, log in, `make gpu-health` must exit 0.
6. **Repair test [GPU][HUMAN]:** `pruefstand-lock sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster stop-ollama`,
   then `make gpu-repair`: exactly one server started detached, the day models loaded.
7. **[DOCKER] rerank-cpu:** `mkdir -p "$PRUEFSTAND_HOME/qdrant"`, then `make up PROFILES="core gpu dev"` and
   `docker compose --profile gpu --profile dev exec rerank-cpu python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8201/health').status)"`
   (200 once the model has loaded), `docker image inspect` for the image digest, `make down`.
   The executor stack must publish no rerank host port: it does not (T6.2a resets `ports`).

## Tests

`uv run pytest infra/gpu/tests infra/cluster/tests` (offline). Script tests put stub `ssh`, `curl`, `df`, `pgrep` on a
restricted `PATH` and a fake `/proc` and `cluster.env` under a temp dir (`gpu_testkit.py`, `gpu_world.py`); there are no
fake models. `rerank_app.py` is tested with scores recorded from the real model (`rerank/record_scores.py`). The
`gpu` smoke tests (`packages/pruefstand/tests/gpu/test_endpoints.py`) run only on the VM: `make test-gpu-locked`.
