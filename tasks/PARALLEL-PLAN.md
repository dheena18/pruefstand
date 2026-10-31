# Prüfstand — parallel build plan (waves for multiple coding agents)

Source of truth for tasks, dependencies and shared files: `tasks/TASKS.md` ("Depends" column, "Parallel
lanes", shared-file notes). This plan only **schedules** them into waves; if the two disagree, `TASKS.md`
wins and this file is fixed. Round 10 (`docs/planning/reviews/round10-resolution.md`) adds **T0.7**
(TrueNAS VM setup; T3.1a and T6.2a depend on it) and makes the VM `pruefstand-exec` the machine where all
agents run (VS Code Remote-SSH, Z7). Round 11 (`round11-resolution.md` Y1, Y6) makes the VM's executor
run as the system user `pruefstand` beside the agents, with one host-wide GPU lock and separate dev ports.
A wave is executed by one lead agent with `prompts/_lead-agent.md`.

## 1. Rules (binding for every wave)

1. **One task = one agent = one worktree = one branch = one PR.** Branch name from the prompt header
   (`<type>/<ID>-<slug>`); worktree `~/code/wt/<ID>` created from `origin/main` at wave start. Exception
   written into `TASKS.md` itself: T5.3 has two PRs (sets 1–5 first, `legal_hard` after T4.7b, D161).
   Every new worktree gets the git-ignored `.env` as a symlink (`ln -s ~/code/pruefstand/.env
   ~/code/wt/<ID>/.env`, never committed; Y6.6).
2. **Never two agents on one file.** A task owns the files in its prompt's "Files to create / change".
   Shared files (`Makefile`, `mk/*.mk` of other tasks, root `pyproject.toml`, `.gitignore`, `.env.example`,
   `DATA_LICENSES.md`, `.importlinter`, package dependency lists, `docs/decisions.md`, `docs/ops/secrets.md`,
   `tasks/TASKS.md`, `docs/engineering/test-matrix.md`, `scripts/models/record_cassettes.sh`,
   `.github/workflows/live-e2e.yml`, `.github/workflows/ci.yml` (T0.2, T1.13, T3.7, T6.2b, T7.4, T9.1a,
   T9.2), `cli/__init__.py` + `cli/stubs.py`, `examples/live/pruefstand.yaml`,
   `pipeline/run.py`, `docker-compose.yml`, `core/protocols.py`, `core/data/law_aliases.yaml`, and the
   `§0.2` rows of `docs/engineering/gpu-cluster.md`) are edited **only as the task's own hunk/rows in the
   task's last commit**. `uv.lock` is never merged: take `main`'s and re-run `uv lock`.
3. **Explicit no-parallel pairs** (TASKS.md lanes): T6.1 ∦ T2.5 (cli), T6.1 ∦ T5.1 / T5.2b / T5.4
   (`pipeline/run.py`, `examples/live/pruefstand.yaml`); T4.4 only after T1.8 and T2.4 are merged. The
   waves below already respect them.
4. **Rebase on `main` before opening the PR** and again before merge; re-run `make check` after every
   rebase.
5. **An agent that needs a file owned by a running task stops and reports** (file, why, proposed hunk) to
   the lead; it never edits that file. The lead either defers the change to a follow-up after the owner
   merges or moves the task to the next wave.
6. **Interface changes stop the wave for that task** (`docs/engineering/ai-workflow.md` §4): the agent
   writes the one-paragraph proposal; the human approves or rejects; dependants in the same wave pause.
7. **Shared hardware (Y1):** GPU work runs only through `pruefstand-lock <cmd>` (or the `mk/gpu.mk`
   targets that use it), i.e. under the one host-wide lock `/var/lib/pruefstand/gpu.lock` that the
   executor (user `pruefstand`) takes too (gpu-cluster.md §8), so GPU steps of parallel tasks, gated PRs
   and the nightly (22:00–06:00 Europe/Berlin) queue on the same file. Agents never touch
   `/var/lib/pruefstand/**` or `/home/pruefstand/**` directly (`security.md` C18). Agent stacks use
   compose profile `dev` with `PORT_OFFSET=10000` (`docker.md` §3; prefer `make up PROFILES="…"`; a raw
   `docker compose` only after `make ports-env` has made the dev ports literal in `.env`, verified by
   `make check-ports`; R12 A12-M4, A13-M6, D310), so they never collide with the executor stack. All worktrees
   share **one** dev compose project (`COMPOSE_PROJECT_NAME=pruefstand-dev`, same `.env`, fixed dev ports), so a
   **stack session is one lock hold** from `up` to `down` (A13-M8): `make stack-run CMD="…"` (T0.3) =
   `flock ~/pruefstand/stack.lock sh -c 'make up …; <checks>; make down'`; `make test-e2e`, `make test-live`,
   `make test-integration` and every Done-when that brings a stack up run that way (owner user; the executor
   does not use the lock). Another agent's `up` can therefore never replace your containers between your `up`
   and your checks; only one agent stack is up at a time. Done-when checks against internal-only services use `docker compose exec` or the dev ports
   (Y6.5). RAM on the 64 GB VM: executor stack ≤ 16 GB (incl. `rerank-cpu` 6 GB), optional demo ≤ 8 GB,
   one agent stack ≤ 16 GB, at most 6 agent sessions in the rest.
8. **Max parallel agents per wave: 6** (owner review capacity is the real limit: ≈ 70 PRs in total).
   `[HUMAN]` / `[GPU]` steps of a wave are batched for the owner (§3 of `_lead-agent.md`).
9. Merge order inside a wave: lower layers first (`core` → `llm`/`ingest`/… → `metrics` → `gate`/`runner`
   → `pipeline`/`cli` → apps → infra/docs), then the task with the most shared-file hunks last, so each later
   PR rebases over fewer conflicts.

## 2. Waves

Columns: **Owns** = main paths (authoritative list: the prompt). **Env**: `GPU`, `DOCKER`, `NET`, `HUMAN`.
**Est.** from TASKS.md (AI hours). Shared hunks are listed separately per wave.

### Wave 0 — human bootstrap (0 agents)

| Task | Branch | Owns | Env |
| --- | --- | --- | --- |
| T0.7 S1–S2 (human part first) | — | create VM `pruefstand-exec` (64 GB), VS Code Remote-SSH | HUMAN |
| T0.0 | `main` (planning-pack commit) | prerequisites **on the VM** first (Z7; WSL optional), public repo, planning pack pushed, `gh models`; `gh` on the VM with the public-repo-only fine-grained token, `gh api repos/dheena18/pruefstand-gate` → 404 (R12 N4.4) | HUMAN, NET |

Human between waves: confirm Remote-SSH works and `git`, `uv`, `docker` verify commands pass on the VM.

### Wave 1 — scaffold (1 agent)

| Task | Branch / worktree | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T0.1 | `chore/T0.1-repo-scaffold` → direct push to `main` (bootstrap exception) | root config, all Make targets, uv workspace, import-linter, `.claude/settings.json` | – | 3 |

Checkpoint: `make check` green on `main`; `pruefstand version`.

### Wave 2 — foundations (5 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T0.2 | `ci/T0.2-ci-pipeline` | `.github/workflows/{ci,security,cassettes}.yml`, `live-e2e.yml` skeleton, Dependabot, PR template, CODEOWNERS | NET | 4 |
| T0.3 | `chore/T0.3-docker-compose` | `infra/docker/**`, `docker-compose.yml` (creates it), `build-images.yml` | DOCKER | 3 |
| T1.1 | `feat/T1.1-core-models` | `packages/pruefstand/src/pruefstand/core/**` (not `config/`, `citations/`), schemas export | – | 4 |
| T2.1 | `feat/T2.1-data-downloads` | `data/**`, `scripts/check_no_raw_data.py` | NET | 3 |
| T0.7 | `chore/T0.7-truenas-vm-setup` | `infra/vm/**` (user `pruefstand`, `/var/lib/pruefstand`, `pruefstand-lock`, system tunnel unit, NAS automount), gpu-cluster.md §0.2 rows V1–V7 | HUMAN, NET | 3 |

Shared hunks: `.env.example` (T0.3, T0.7), `DATA_LICENSES.md` (T2.1), `docs/ops/secrets.md` (T0.7).
Merge order: T0.2 → T1.1 → T2.1 → T0.3 → T0.7.
Checkpoint: `make check`; `make stack-run CMD="curl -sf localhost:16333/readyz"` (with `PROFILES="core dev"`; DEV13-08: never a raw `docker compose up` here); `infra/vm/vm_check.sh` (never restarts Docker, A13-M11).
Human: T0.7 S3–S7 (NAS automount with sudo, `ssh-copy-id` as `pruefstand` with the cluster password once,
VM reboot test, TrueNAS host reboot test V7).

### Wave 3 (4 agents + T0.5 human)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.2 | `feat/T1.2-config` | `core/config/**`, `core/data/model_families.yaml`, creates `examples/live/pruefstand.yaml` | – | 3 |
| T1.5a | `feat/T1.5a-citation-parser` | `core/citations/**`, creates `core/data/law_aliases.yaml` | – | 3 |
| T0.4 | `docs/T0.4-docs-site` | `mkdocs.yml`, `docs.yml`, site build scripts | NET | 2 |
| T0.6 | `docs/T0.6-cluster-feasibility` | `infra/cluster/feasibility/**` (tunnel check on the existing tunnel or temporary port 21434, Y1.4, ADR-0018; detached-process-survives-logout check, Y5.4), `scripts/models/quota_probe.py`, gpu-cluster.md §0.2 rows C1–C9, ci-cd.md §1.1a | GPU, NET, HUMAN | 2 |
| T0.5 (human) | — | GitHub settings, App `pruefstand-bot` | HUMAN | 1 |

Shared hunks: `live-e2e.yml` (T0.6 input `probe_quota`). Merge: T1.2 → T1.5a → T0.4 → T0.6.
Checkpoint: `make check`, `make docs`; T0.6 verdict `go`/`go-with-conditions` (else stop GPU lane).
Human: T0.5; T0.6 probe over SSH + admin questions; after merge, the 24-hour quota probe follow-up PR (S7).

### Wave 4 (6 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.6 | `feat/T1.6-gate-stats` | `gate/stats/**` | – | 5 |
| T1.5b | `feat/T1.5b-deterministic-metrics` | `metrics/deterministic/**`, metric registry | – | 4 |
| T1.3 | `feat/T1.3-adapters` | `adapters/**`, target OpenAPI, `tests/contract/**` | – | 4 |
| T1.4 | `feat/T1.4-llm` | `llm/**`, creates `scripts/models/record_cassettes.sh`; hunk `core/protocols.py` | DOCKER, NET | 4 |
| T2.2 | `feat/T2.2-gii-loader` | `ingest/gii/**`, `ingest/text.py`; hunk `law_aliases.yaml` | – | 4 |
| T3.1a | `feat/T3.1a-gpu-cluster-services` | `infra/cluster/*.sh`, `infra/gpu/**`, `mk/gpu.mk`; hunk `docker-compose.yml` | GPU, HUMAN | 3 |

Merge: T1.6 → T1.5b → T1.3 → T1.4 → T2.2 → T3.1a.
Checkpoint: `make check`; `make test-live` (llama.cpp container, under `stack.lock`); `pruefstand-lock make test-gpu`.
Human: T3.1a S2b (move/re-pull the qwen model into `ollama-models/`) and S8 bring-up in day/night/datagen.

### Wave 5 (6 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.7 | `feat/T1.7-gate-policy` | `gate/policy*`, `gate/cause*` | – | 4 |
| T1.8 | `feat/T1.8-runner-store` | `runner/**`, `store/artifacts*`, `store/kv.py`; hunk `core/protocols.py` | – | 4 |
| T2.3 | `feat/T2.3-oldp-loader` | `ingest/oldp/**` + own tests | – | 3 |
| T2.4 | `feat/T2.4-eurlex-loader` | `ingest/eurlex/**` + own tests; hunk `law_aliases.yaml` | – | 4 |
| T1.13 | `feat/T1.13-rag-demo-v0` | `apps/rag-demo/**`; hunks `docker-compose.yml` (`live`), `record_cassettes.sh` | DOCKER, NET | 5 |
| T3.1b | `feat/T3.1b-model-benchmark` | `experiments/model_selection/**`, `mk/bench.mk`, pins in `infra/gpu/models.yaml` | GPU, NET, HUMAN | 3 |

Merge: T1.7 → T1.8 → T2.3 → T2.4 → T1.13 → T3.1b.
Checkpoint: `make check`; `make stack-run CMD="curl -sf localhost:18000/v1/health"` (with `PROFILES="core live dev"`; DEV13-08) → rag-demo `/v1/health`; `pruefstand-lock make test-gpu`.
Human: T3.1b benchmark runs + scoring 10 items; datagen scoring needs a **weekend** (`switch-mode.sh datagen` sets `MAINTENANCE` itself, Y6.2).

### Wave 6 (3 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.9 | `feat/T1.9-report` | `report/**` (PR comment, JSON, publisher) | – | 3 |
| T4.4 | `feat/T4.4-perturb-deterministic` | `perturb/deterministic/**`; hunks `core/protocols.py`, `law_aliases.yaml` | – | 4 |
| T3.2 | `feat/T3.2-rag-demo-gpu-profile` | `apps/rag-demo/src/rag_demo/models.py`, `configs/rag.gpu.yaml`, `/v1/info` | – | 3 |

Merge: T1.9 → T4.4 → T3.2. Checkpoint: `make check`; `make schemas-fresh`.

### Wave 7 (2 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.10 | `feat/T1.10-pipeline-cli` | `pipeline/**`, `cli/**` (creates), `examples/live/mini.yaml`; hunks `record_cassettes.sh`, `examples/live/pruefstand.yaml` | – | 3 |
| T3.3 | `feat/T3.3-german-analyzer` | `apps/rag-demo/.../analysis/**` (moves T1.13 tests) | – | 4 |

Merge: T1.10 → T3.3. Checkpoint: `make check`; `pruefstand run` against the `live` stack (manual smoke).

### Wave 8 (3 agents; T6.1 deliberately not here)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T1.11 | `test/T1.11-fixtures-e2e` | `datasets/fixtures/**`, e2e tests; hunk `examples/live/pruefstand.yaml` | DOCKER, NET, HUMAN | 3 |
| T2.5 | `feat/T2.5-tenants-ingest` | `pipeline/ingest.py`, tenant plan, corpus manifest; hunk `cli/__init__.py` | – | 3 |
| T5.1 | `feat/T5.1-llm-hardening` | `llm/` hardening, quota handling; hunks `pipeline/run.py`, `examples/live/pruefstand.yaml` | GPU or NET | 4 |

Merge: T1.11 → T2.5 → T5.1. Checkpoint: `make check`; **`make test-e2e`** (first full tier-1 e2e, under
`stack.lock`). Human: sign off the 40 fixture cases (T1.11).

### Wave 9 (6 agents) → M1

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T6.1 | `feat/T6.1-baseline-store-cache` | `store/baselines*`, RunIndex, target cache; hunks cli, `pipeline/run.py`, `examples/live/pruefstand.yaml` | – | 4 |
| T1.12 | `feat/T1.12-github-action` | `action/**`, `live-e2e.yml` body, `action-selftest.yml`; hunk `examples/live/pruefstand.yaml` | NET | 4 |
| T4.1 | `feat/T4.1-dataset-manifest-splits` | `dataset/manifest*`, splits, HF export | – | 3 |
| T5.2a | `feat/T5.2a-judges-prompts` | `judges/**`, judge prompt files; hunk `record_cassettes.sh` | GPU | 4 |
| T3.4 | `feat/T3.4-indexer` | `apps/rag-demo/.../index/**` | DOCKER, GPU | 4 |
| T2.6 | `feat/T2.6-private-docs-canaries` | synthetic private docs, canary registry scripts | GPU or NET, HUMAN | 4 |

T6.1 and T1.12 both add a hunk to `examples/live/pruefstand.yaml`: allowed (own hunk, last commit), T6.1
merges first. Merge: T6.1 → T4.1 → T5.2a → T3.4 → T2.6 → T1.12.
Checkpoint: `make check`; **tier-1 live**: a real PR with `live-e2e.yml` green + the two deterministic demo
PRs (M1). Human: review private docs + canaries (T2.6).

### Wave 10 (6 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T3.5 | `feat/T3.5-retriever` | `apps/rag-demo/.../retrieval/**` | DOCKER | 4 |
| T4.6 | `feat/T4.6-attacks` | `attacks/**`, `canaries/retired.json` | – | 4 |
| T4.5 | `feat/T4.5-perturb-llm` | `perturb/llm/**`; hunk `record_cassettes.sh` | GPU or NET | 4 |
| T5.2b | `feat/T5.2b-judged-metrics` | `metrics/judged/**`; hunks `pipeline/run.py`, `examples/live/pruefstand.yaml`, `record_cassettes.sh` | – | 3 |
| T5.3 (PR 1: sets 1–5) | `feat/T5.3-calibration-sets` | `datasets/calibration/**` (not `legal_hard`), data card | NET | 2 |
| T4.2 | `feat/T4.2-qa-generation` | `dataset/generate*`, prompts; hunk `record_cassettes.sh` | GPU (datagen weekend) | 4 |

Merge: T3.5 → T4.6 → T4.5 → T5.2b → T5.3 PR 1 → T4.2.
Checkpoint: `make check`; `pruefstand-lock make test-gpu`. Human: datagen **weekend** for T4.2 (and T4.5
if run in datagen mode); `switch-mode.sh datagen` sets `MAINTENANCE`, `switch-mode.sh day` removes it.

### Wave 11 (3 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T6.4 | `feat/T6.4-html-evidence` | `report/html*`, `core/models/evidence*`; hunks `live-e2e.yml`, `pipeline/run.py`, `examples/live/pruefstand.yaml` | – | 3 |
| T4.3 | `feat/T4.3-qa-filters` | `dataset/filters*` | – | 3 |
| T3.6 | `feat/T3.6-generator` | `apps/rag-demo/.../generation/**`, prompt files | GPU | 4 |

Merge: T6.4 → T4.3 → T3.6. Checkpoint: `make check`; `pruefstand-lock make test-gpu`; rag-demo with `rag.gpu.yaml` answers with citations.

### Wave 12 (3 agents) → M2

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T3.7 | `feat/T3.7-tenant-isolation-tests` | rag-demo isolation/quality tests | DOCKER, GPU, HUMAN | 4 |
| T4.7a | `feat/T4.7a-review-tool` | `tools/review_app/**`, `build-dataset` orchestration; hunks `cli/__init__.py`, `cli/stubs.py` | – | 3 |
| T8.1 | `feat/T8.1-dashboard-scaffold` | `apps/dashboard/**` (creates), `ui.yml`; hunks cli, `live-e2e.yml` | – | 3 |

Merge: T4.7a → T3.7 → T8.1 (T4.7a before T8.1: both touch the cli hunk and `stubs.py` tests). Checkpoint: `make check`, `make ui-check`; M2 evidence. Human: 10 manual German questions (T3.7).

### Wave 13 (2 agents) → M3

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T4.7b | `feat/T4.7b-dataset-release` | cross-family review, closed-book tags, v1 release | GPU, NET, HUMAN (8 h) | 3 |
| T8.2a | `feat/T8.2a-dashboard-runs` | `apps/dashboard/` runs list + detail, i18n | – | 3 |

Merge: T8.2a → T4.7b. Checkpoint: `make check`, `make ui-check`; HF dataset v1 (M3). Human: 50-item spot check.

### Wave 14 (3 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T5.3 (PR 2: `legal_hard`) | `feat/T5.3-legal-hard` | `datasets/calibration/legal_hard/**`; passes (D230, D246): day pass (answers) → datagen weekend (llama review) → offline `--pass build` | GPU, HUMAN (weekend) | 1 |
| T6.2a | `feat/T6.2a-gate-executor` | private repo `pruefstand-gate`, orchestrator, `llm-proxy`, runner on the VM | GPU, HUMAN | 4 |
| T8.2b | `feat/T8.2b-dashboard-diff` | dashboard diff, slices, cases pages | – | 3 |

Merge: T5.3 PR 2 → T8.2b → T6.2a. Human: datagen weekend for T5.3 PR 2; register the persistent runner on
the VM as user `pruefstand`, create `pruefstand-dashboard-data` + scoped PAT (T6.2a [HUMAN]).

### Wave 15 (2 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T5.4 | `feat/T5.4-judge-calibration` | `judges/drift.py`, calibration runs; hunks cli (`judge-drift`), `live-e2e.yml`, `examples/live/pruefstand.yaml` | GPU | 4 |
| T6.2b | `feat/T6.2b-gate-workflows` | public `build-images.yml`, `executor-health.yml`, `gate-router.yml`; private workflows | GPU, NET | 4 |

Merge: T5.4 → T6.2b. Checkpoint: first tier-2 gate run end to end on a PR the owner dispatched (`gate-executor.yml -f pr=N` from the browser or mobile app; no label, round 13 P1.2), with `pruefstand/gate` created by `pruefstand-bot[bot]`.

### Wave 16 (3 agents)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T6.3 | `feat/T6.3-noise-thresholds` | noise study, MDE tables | GPU (several nights) | 3 |
| T7.3 | `feat/T7.3-rq1-grid` | `experiments/rq1/**`, `evidence_recall` | GPU | 4 |
| T9.1a | `feat/T9.1a-release-pipeline` | `release-please.yml`, `release.yml` | NET, HUMAN | 3 |

GPU steps of T6.3 and T7.3 queue on the lock (T6.3 first). Merge: T9.1a → T7.3 → T6.3.

### Wave 17 (2 agents) → M4 (MVP)

| Task | Branch | Owns | Env | Est. |
| --- | --- | --- | --- | --- |
| T6.5 | `demo/T6.5-*` + `docs/T6.5-mvp-evidence` | demo PRs (throwaway), evidence doc | GPU, HUMAN | 2 |
| T9.1b | `feat/T9.1b-marketplace-hf` | Marketplace sync, `dataset-release.yml` | NET | 2 |

### Waves 18–23

| Wave | Tasks (agents) | Merge order | Checkpoint / human |
| --- | --- | --- | --- |
| 18 | T7.1a (`benchmarks/mutations/**` core), T8.3 (`apps/dashboard` Playwright/axe/Lighthouse) — 2 | T7.1a → T8.3 | `make check`, `make ui-check` |
| 19 | T7.1b (mutations M11–M20), T8.4 optional (demo API + try-it) — 2 | T7.1b → T8.4 | — |
| 20 | T7.2 (RQ3 runner) — 1 | — | GPU-heavy; many executor runs |
| 21 | T7.4 (`make experiments`, mutmut), T8.5 (Pages deploy via `docs.yml`, leak-probe job, optional VM demo behind Cloudflare Tunnel) — 2 | T7.4 → T8.5 | M5; M6 after deploy smoke. Human: enable Pages; Cloudflare account only if the demo is built |
| 22 | T9.2 (README, quickstart test), T9.3 (technical report) — 2 | T9.2 → T9.3 | M7 candidate. Human: report edits |
| 23 | T9.4 (human) — 0 | — | M7 |

Optional Phase 10 (T10.1–T10.4) fills free slots from Wave 17 on (after T9.1a); T10.1 and T10.4 each add
a cli registration hunk, so not in the same wave as another cli-hunk task without merge-order care.
T5.3-opt runs whenever a German speaker turns up, after T5.4.

## 3. Integration checkpoint (after every wave)

Run by the lead on `main` after the last merge of the wave, on the VM:

1. `git switch main && git pull --ff-only && uv sync --all-packages --all-extras`
2. `make check` (must be green; no skipped or quarantined test added in this wave without an issue)
3. `make schemas-fresh`; `make docs` once T0.4 is merged; `make ui-check` once T8.1 is merged
4. Under `stack.lock` (one hold from `up` to `down`, A13-M8): `make test-integration`, and from Wave 8 on `make test-e2e`; from Wave 9 on, a real
   PR's `live-e2e.yml` (tier 1 live) green in CI
5. Through `pruefstand-lock` (host-wide `gpu.lock`), from Wave 4 on: `make gpu-health`, `make test-gpu`; from Wave 15 on, one PR
   gated by the executor after the owner's dispatch (P1.2)
6. Record the evidence in the wave's checkpoint PR (`chore/wave-<N>-checkpoint`: TASKS.md progress ticks,
   decisions appended, nothing else)

A red checkpoint blocks the next wave; the fix is its own `fix/` PR.

## 4. Calendar estimate (planning, not a promise)

| | Serial (one session at a time) | Waves (≤ 6 agents) |
| --- | --- | --- |
| AI hours | ≈ 231 h (sum of TASKS.md estimates, core, incl. T0.7) | ≈ 84 h on the wave critical path (sum of each wave's longest task) |
| Owner time | review ≈ 30 h + human steps ≈ 27 h | same review + human steps, plus ≈ 1 h checkpoint × 23 waves |
| Fixed waits | datagen weekends, 24-h quota probe, several nights for T6.3, 8 h dataset review | same, but overlapped with other lanes where the plan allows |
| Calendar (part-time owner, ~10–12 h/week) | **20–26 weeks** (TASKS.md), M4 ≈ week 12–14 | **≈ 12–15 weeks**, M1 ≈ week 4, M4 ≈ week 8–10 |

The bottleneck moves from AI time to **owner review and owner-only steps**: ≈ 70 PRs still need a
review each (15–60 min). Waves with 6 PRs need a review block of 3–5 h. GPU-heavy waves (10, 15–17, 20)
serialise on the lock and on weekend datagen, so they gain least.
