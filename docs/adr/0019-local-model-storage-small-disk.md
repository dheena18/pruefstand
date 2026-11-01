# 0019 — Models on the cluster's own disk, one judge, no local 70B datagen, data root on the VM disk

- Status: Accepted
- Date: 2026-10-31
- Tasks: T0.6, T0.7, T2.6, T3.1a, T3.1b, T4.2, T4.5, T4.7a, T4.7b, T5.1, T5.2a, T5.3, T5.4, T6.1, T6.2a, T6.2b,
  T7.1a, T7.3, T9.3
- Amends: [ADR-0018](0018-single-ollama-server.md) (model dir, KV cache type, modes, start script),
  [ADR-0009](0009-litellm-providers.md) (family plan, judges, datagen provider),
  [ADR-0010](0010-qdrant-hybrid-tenant-filter.md) (embedding swaps on the small disk),
  [ADR-0004](0004-baseline-store-git-branch.md) (baseline files on the VM disk, backups)
- Supersedes: the two-judge plan (PR judge `mistral`, nightly judge `gemma` 27B-class; D112, D141, D168, D205,
  D319), the local 70B `llama` datagen model and the `datagen` mode (D87, D172, D230, D246), the NAS model dir
  (D197, D207, D324 model-dir part), the NFS/automount data root (D227, D254) and the `nas_unavailable`
  infra error kind (D245)

## Context

The owner checked the real machines on 2026-10-31 and decided to "manage with whatever we have"
(`docs/ops/setup-log.md` §6, §7):

- **Cluster disk.** `/data` on `cairo-s101lp` has about **14 GB free** next to the 29 GB generator
  `qwen3.8:27b-q8_0`. The NAS can be mounted on the cluster (rclone WebDAV, `/data/dheena/truenas-ollama`),
  and `OLLAMA_MODELS` on it worked, but the link gave **~6 MB/s** (≈ 80 min to load the generator after every
  Ollama restart). That is not usable for gates.
- **Model set.** With ~14 GB free, the cluster can hold the generator, `bge-m3` (~1.2 GB) and **one** judge of
  ~8 GB, keeping ≥ 2 GB free. A 24B PR judge plus a 27B nightly judge (~15 + ~17 GB) and a 70B datagen model
  (~43 GB) do not fit.
- **Owner's start script.** The cluster already runs one server from `~/start-ollama.sh` with
  `OLLAMA_MODELS=/data/dheena/Models`, `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_KEEP_ALIVE=24h`,
  `OLLAMA_NUM_PARALLEL=4`, `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
  `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_NOPRUNE=1`, `OLLAMA_HOST=127.0.0.1:11434`, `CUDA_VISIBLE_DEVICES=0,1`
  (setup log §7).
- **VM data root.** The VM cannot reach its own TrueNAS host over NFS (NIC attached directly to the physical
  NIC; a bridge did not work on the first try). The VM's system disk is a 500 GB zvol on the TrueNAS pool with
  ~450 GB free, so `/mnt/pruefstand` is a plain directory on it (setup log §6).
- **Copying scripts.** With no shared folder between VM and cluster, the cluster scripts need another way in.

## Decision

1. **Models on the cluster's own disk.** `OLLAMA_MODELS=/data/dheena/Models`. The NAS/rclone path is rejected
   (~6 MB/s). Model set that fits:

   | Role | Tag | Family (Ollama → plan) | Size |
   | --- | --- | --- | --- |
   | Generator (kept) | `qwen3.8:27b-q8_0` (digest `8f5fb6b7…1766039`) | `qwen35` → `qwen` | ~29 GB |
   | Embeddings | `bge-m3` | plan family `bge` | ~1.2 GB |
   | **Judge** (PR **and** nightly) | Gemma 3 12B Q4: `gemma3:12b` (**verify** tag and digest in T3.1b) | `gemma3` → `gemma` | ~8 GB |

   At least **2 GB stay free** on `/data`. `core/data/model_families.yaml` maps `qwen35` → `qwen`,
   `gemma3` → `gemma` (and the GitHub Models datagen model to its own family, item 3).
2. **Server settings of record** are the owner's `~/start-ollama.sh` (setup log §7): `OLLAMA_MAX_LOADED_MODELS=3`
   (generator + embeddings + judge), `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_NUM_PARALLEL=4`,
   `OLLAMA_CONTEXT_LENGTH=8192` (default only; Prüfstand always sends `num_ctx`), `OLLAMA_KV_CACHE_TYPE=q8_0`
   (replaces ADR-0018's `f16`; the KV type is part of the serving facts, so a change is a new
   `eval_fingerprint`), `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_NOPRUNE=1`. T3.1a **reuses** this script: when no
   server answers, `start-ollama.sh` from the Prüfstand bin dir runs `setsid nohup ~/start-ollama.sh >
   /data/dheena/ollama.log 2>&1 < /dev/null &`; it never starts a second server and never writes its own server
   environment. `cluster.env` holds only the expected values that `status.sh` compares (WARN on a difference)
   and the paths.
3. **One judge for PR and nightly.** The separate PR judge (`mistral`) and nightly judge (`gemma` 27B) are
   removed. `gemma3:12b` grades both tiers at catalogue `num_ctx` 12 288 (D306 rule unchanged); `judge_epoch`,
   `judge_serving`, judge drift, calibration (SPEC §7.5) and the `judge_fallback` rule are unchanged. Nightly
   uses the same judge, so the nightly mode switch no longer swaps judges; `day` and `night` load the same
   models (the names stay for logs and the window). If the judge fails calibration (T5.4), candidates are
   pulled one at a time (item 5); with none passing, judged metrics stay informational (SPEC §7.5).
4. **No local 70B datagen; no `datagen` mode.**
   - Questions, references and perturbation rewrites from **public** law/decision/EUR-Lex text are generated
     with a pinned **GitHub Models free-tier** model of a family that is neither `qwen` nor `gemma` (T4.2 pins
     it; **verify** the model, its rate limit and output terms). The `LLMPolicy` data guard allows this for
     public text only; T4.2 runs resumable, cached batches within the daily quota.
   - **Private docs, canaries and held-out data** are generated **locally** on the cluster with the judge model
     `gemma3:12b` (role `DATAGEN`, `ollama/<tag>`), never by an external provider. Private docs are contexts
     for leak probes, which are graded deterministically (canary and tenant checks), so the judge never grades
     a reference it wrote.
   - Model reviews (T4.7b, SPEC §3.5) use the local `gemma3:12b` in **reject-only** mode for every split: its
     `fix` may change only the question; a wrong reference → `reject` and regeneration with the GitHub Models
     datagen model. The gating judge therefore never writes or rewrites a reference. The `legal_hard` reviewer
     (T5.3) is the GitHub Models datagen model (public answers only), so the judge under calibration does not
     pick its own positives.
   - `switch-mode.sh datagen`, `make gpu-large-up` and the catalogue role `large` are removed.
     `/var/lib/pruefstand/MAINTENANCE` stays: the owner (or a task whose prompt says so) sets it for model swaps.
5. **Swap rule (small disk).** When space is needed: under the GPU lock and with `MAINTENANCE` set,
   `ollama rm` a **non-generator** model, then `ollama pull` the new one (`fetch-model.sh`, digest check), and
   restore the standard set afterwards. RQ2 judge comparisons (T5.4) pull, measure and delete **one** candidate
   at a time. RQ1/M3 embedding swaps (e5) and M11 (smaller Qwen) use small tags that fit next to the set, or
   this rule. `health.sh` warns when `/data` has < 2 GB free.
6. **Data root on the VM disk.** `PRUEFSTAND_DATA_ROOT=/mnt/pruefstand` is a plain directory on the VM's
   zvol: no NFS, no `mnt-pruefstand.automount`, no mount unit, no `CLUSTER_NAS_ROOT`. The preflight checks that
   the directory exists, is writable by `pruefstand` and has ≥ 20 GB free; else the job ends with
   `infra_error="data_root_unavailable"` (replaces `nas_unavailable`). Backups: TrueNAS periodic snapshots of
   the VM zvol (daily, keep 14) plus the weekly `age`-encrypted bundle copied to the owner's laptop.
7. **Cluster scripts over SSH.** `deploy-cluster-bin.sh` copies `infra/cluster/*.sh`, `cluster.env` and
   `SHA256SUMS` from the VM checkout over SSH (`ssh cairo-s101lp 'cat > …partial && mv …'`) into
   `/data/dheena/pruefstand-bin` on the cluster (a few KB). The VM invokes them as
   `ssh "$CLUSTER_SSH_HOST" bash /data/dheena/pruefstand-bin/<script>.sh`. The Ollama log is
   `/data/dheena/ollama.log` (owner's start command).
8. **Budgets.** VRAM and time numbers for the one-judge set are planning values: **verify in T3.1b**.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Models on the NAS through rclone (tried) | ~6 MB/s: ≈ 80 min per generator load after every restart |
| Keep two judges, swap from the NAS at night | Same load speed problem; 27B judge does not fit the disk next to the 24B one |
| Local 70B datagen on weekends | ~43 GB does not fit the disk; a NAS load would take hours |
| GitHub Models for private docs | Breaks the data guard: private docs and canaries never leave our machines |
| NFS share from TrueNAS to the VM | The VM cannot reach its host without a bridge; the VM disk is large enough |
| Ask the cluster admin for more disk | Open; when granted, a new ADR may restore a larger judge |

## Consequences

- Positive: models load from local disk (generator in seconds, setup log §7); no network mount on either
  machine; one judge means no night swap, no `judge_fallback` from a missing night judge and one calibration.
- Negative: one judge family (`gemma`) grades everything, so judge diversity comes only from RQ2's GitHub Models
  arms and swapped candidates; 12B is weaker than the planned 24B/27B judges (calibration decides whether it
  gates). Datagen depends on the GitHub Models quota and its model's output terms. The RQ2 size contrast moves
  to `gemma3:4b` vs `gemma3:12b`; the 70B arm is gone.
- The disk stays nearly full: every extra model is a swap under `MAINTENANCE`, and an unexpected
  `ollama pull` by another user can fill it (preflight digest check and the `/data` free-space WARN).
- Follow-ups: T3.1b pins `gemma3:12b` and measures VRAM/time; T4.2 pins the GitHub Models datagen model;
  the NAS dataset `/mnt/SDD/SSD/Ollama` held Ollama's identity key; moved out of the share on 2026-11-01 (setup log §7).
