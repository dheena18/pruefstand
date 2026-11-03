# CLAUDE.md — ground rules for every session in this repo

Prüfstand is an open-source release gate for German-language RAG. The authoritative spec is
`docs/spec/SPEC.md`; the cross-module contracts are `docs/architecture/interfaces.md`; decisions are
in `docs/decisions.md` and `docs/adr/`. Tasks are in `tasks/TASKS.md`, one prompt per task in `prompts/`.
The UI source of truth is `docs/design/ui-spec.md` (D134); the per-symbol test plan is
`docs/engineering/test-matrix.md` (D133).

These rules are not optional. If a rule blocks you, stop and explain why in one paragraph; do not
work around it.

## 1. How to work

1. Work on **exactly one task ID** per session/branch (e.g. `T1.6`). Read its prompt file fully first.
2. Before writing code, post a short plan: files to create/change, public interfaces, tests you will write.
3. **Tests first.** Write the failing tests, then the implementation, then refactor.
4. Stop when every "Done when" item passes and show the evidence (command + output).
5. Never change an interface in `docs/architecture/interfaces.md`, a schema, or an ADR silently. If a
   change is needed: write one paragraph (what, why, impact), update the doc + ADR in the same PR,
   and flag it in the PR description under **Interface changes**.
6. Do not start work belonging to another task. Note it under **Follow-ups** in the PR.
7. Update `docs/decisions.md` (one line per decision) and any diagram your change affects.
8. On the VM, never read, write or delete anything under `/var/lib/pruefstand/**` or `/home/pruefstand/**` (the
   executor's lock, state, key and secrets; R11 D213). GPU work goes through `pruefstand-lock <cmd>`; never edit
   or remove `/var/lib/pruefstand/MAINTENANCE` by hand unless your prompt is a model-swap task that says so (ADR-0019).
   **Exception (D451, owner decision 2026-11-02): the lead agent may create and remove that one file, and remove or swap
   catalogue models, under the conditions in `docs/ops/lead-handoff.md` section 6** (only models listed in
   `infra/gpu/models.yaml`, only through the wrapper / `make gpu-pull` / `gpu-rm`, under `pruefstand-lock`, only while no
   gate or nightly runs, always removing `MAINTENANCE` again, every change logged in `docs/engineering/gpu-cluster.md` §8;
   never the generator `qwen3.8:27b-q8_0`, not even to free space).
   Task agents never do this; nothing else under `/var/lib/pruefstand/**` changes.
9. GitHub from the VM (R12 N4.4, D257): `gh`/git on the VM authenticate with the owner's **fine-grained token limited
   to the public repo** (contents + pull requests + workflows write; Workflows is required to push `.github/workflows/**`, D284; no administration, no access to `pruefstand-gate` or
   `pruefstand-dashboard-data`), never `gh auth login --web`. What this token can do is exactly (R13 P1.3, D289):
   push branches, open and update PRs and comments, and push workflow files of the public repo. None of it can
   produce the required status `pruefstand/gate` (the ruleset pins it to the App `pruefstand-bot`, D287; a status a
   branch workflow posts with `GITHUB_TOKEN` does not count) and none of it can start tier 2 (the only PR trigger is
   the owner's `workflow_dispatch` of the private `gate-executor.yml`, D288; there is no `run-gate` label). Never use
   `gh pr merge --admin`, never touch the private repo or rulesets: those are the owner's actions from the Windows
   browser (or the GitHub mobile app for the dispatch).

## 2. Repository map

```text
packages/pruefstand/src/pruefstand/   the installable gate package (layered, see §4); CLI = package cli/
apps/rag-demo/src/rag_demo/           reference RAG app (system under test; never imports pruefstand)
apps/dashboard/                       Next.js + TypeScript dashboard (reads run artefacts only)
action/                               GitHub Action (action.yml + Dockerfile)
benchmarks/mutations/                 seeded regressions + no-ops (RQ3)
experiments/                          RQ1–RQ3 scripts (fixed seeds), outputs CSV/PNG
data/                                 download scripts + manifests only, never raw data
datasets/fixtures/                    small hand-written test cases used in CI
docs/                                 spec, ADRs, architecture, engineering, report
infra/                                docker, compose, deploy configs
infra/gpu/                            VM-side GPU tooling: models.yaml, endpoints.yaml, switch-mode/health/fetch-model,
                                      rerank-cpu, compose.gpu.yml (T3.1a); all run on the VM
infra/cluster/                        scripts for cairo-s101lp (start/stop/status Ollama, feasibility probe); copied
                                      by the VM over SSH to /data/dheena/pruefstand-bin and run over SSH, never edited
                                      on the cluster (ADR-0019)
infra/vm/                             TrueNAS VM setup (T0.7): user `pruefstand`, `/var/lib/pruefstand`, `pruefstand-lock`,
                                      data root dir check, SSH key, `pruefstand-tunnel.service`, vm_check.sh (R11 D211–D213, ADR-0019)
infra/gate-executor/                  orchestrator + `llm-proxy` (T6.2a); synced to the private executor repo
tools/                                dev-only tools (review/labeling apps); may read datasets/
scripts/                              repo scripts (e.g. mirror_fork_pr.sh for fork PRs)
results/                              experiment outputs (CSV/PNG), regenerated by `make experiments`
schemas/                              generated JSON Schemas + target OpenAPI (`make schemas`)
packages/*/tests/, apps/rag-demo/tests/, tools/*/tests/, infra/gpu/tests/, infra/vm/tests/, infra/cluster/tests/,
infra/gate-executor/*/tests/, scripts/tests/, scripts/*/tests/,
benchmarks/tests/, experiments/                test dirs (pytest testpaths, append-only list set in T0.1; no __init__.py);
                                      R12 N6.3 (D266): each import root's tests stay in <root>/tests/ (or
                                      <root>/<area>/tests/); test basenames may repeat across roots (importlib mode)
tests/                                repo-level tests only (CI workflows, data manifests)
.claude/settings.json                 project Claude Code settings (allowlist + ruff-format hook), created in T0.1
```

**Machines (R10, `docs/planning/reviews/round10-resolution.md` Z1/Z7; numbers in `docs/engineering/gpu-cluster.md`).**

| Machine | Role |
| --- | --- |
| TrueNAS VM `pruefstand-exec` (Ubuntu 24.04, 64 GB) | **primary**: development (VS Code on Windows → Remote-SSH; every coding-agent command runs here, as the owner user) **and** execution as system user **`pruefstand`** (runner, orchestrator, cluster key `/home/pruefstand/.ssh/id_ed25519_cluster`, system unit `pruefstand-tunnel.service`, state; R11 D211). Rootful Docker (group `docker` = `pruefstand` + owner; D213), Qdrant, candidates, `rerank-cpu`, `llm-proxy` (normal container on `gate-net` + `proxy-egress`, candidates use `http://llm-proxy:11500`; tunnel also bound on `172.17.0.1`, firewalled to `proxy-egress`; D242); lock `/var/lib/pruefstand/gpu.lock` and the file `/var/lib/pruefstand/MAINTENANCE` (group `pruefstand`; D212); data root `/mnt/pruefstand` = a plain directory on the VM disk (500 GB zvol on TrueNAS; no NFS, no mount unit; preflight requires it to exist, be writable by `pruefstand` and have ≥ 20 GB free, else `infra_error="data_root_unavailable"`; backups = TrueNAS zvol snapshots + weekly encrypted laptop copy; ADR-0019); `autossh` tunnels to the cluster; firewall rules in Docker's `DOCKER-USER` chain and the own `PRUEFSTAND-INPUT` chain hooked from `INPUT` (container -> `172.17.0.1` hits `INPUT`), both via `pruefstand-firewall.service`, never flushing the ruleset (R12 N4.2, D255, D285) |
| Cluster `cairo-s101lp` (2 × A40) | **Ollama only**: **one** server on `127.0.0.1:11434` for both GPUs (ADR-0018; the running server is reused, started detached with `setsid nohup` only if none runs, never a second one, never `tmux`, R11 D228; GPU placement by Ollama, checked via `/api/ps`; generator/judge separation by the `llm-proxy` model allow-list); start script of record = the owner's `~/start-ollama.sh`; models on the cluster's own disk `/data/dheena/Models` (~14 GB free: generator `qwen3.8:27b-q8_0`, `bge-m3`, **one** judge `gemma3:12b` for PR and nightly, ≥ 2 GB kept free; other models only by the swap rule under `MAINTENANCE`; ADR-0019); Prüfstand scripts in `/data/dheena/pruefstand-bin` (copied over SSH); native `/api/*` only (D219); no checkout, Docker, data, caches or state; reached only by SSH from the VM with the `pruefstand` key (alias `cairo-s101lp`, non-default `Port`; already set up, `docs/ops/setup-log.md`) |
| Windows laptop | VS Code client; WSL2 Ubuntu 24.04 is an **optional** alternative dev shell |

A second, **private** repository `dheena18/pruefstand-gate` (the *gate executor*) holds the
persistent self-hosted runner (on the VM), its trusted workflows, the baselines branch and the held-out canaries. The
public repo never has a self-hosted runner and holds **no secrets for the gate** except the `pruefstand-bot` App key
in environment `gate-router` (usable only by `gate-router.yml` on `main`, R13 D287): the executor *pulls*. A PR runs
tier 2 **only** when the owner dispatches the private `gate-executor.yml` (input `pr`) from the browser or the GitHub
mobile app (R13 P1.2, D288; no `run-gate` label, no PR poll; `main` pushes and nightlies stay automatic); it takes the
gate config, dataset and pruefstand package from trusted `main`, and from the PR only the **tier-2** rag-demo config
(`apps/rag-demo/configs/rag.gpu.yaml`, T3.2; `rag.yaml` is the tier-1 CPU profile; R9 X3.15) and the signed
candidate image (public GHCR package built from the PR **head** SHA, pulled without credentials; R9 X2.4). Gated PRs
get the commit status `pruefstand/gate` from the executor through the GitHub App `pruefstand-bot`; PRs that touch no
gated path get it from the public `gate-router.yml` ("not gated", posted with the same App's token; R9 X2.2, R13 D287,
the only `pull_request_target` workflow, §7); the ruleset pins `pruefstand/gate` to that App (ADR-0005,
`docs/engineering/ci-cd.md`). Executor operation (D100–D110, R9 X2.1–X2.7): a **persistent**
runner (systemd service on the VM, job-start/-complete cleanup hooks); one concurrency group per private workflow plus a host
lock `flock /var/lib/pruefstand/gpu.lock` taken **once per job by the orchestrator** (R11 D211; owner and agent GPU
commands use the same file through `pruefstand-lock <cmd>`, D212; preflight runs after the lock;
`switch-mode.sh`, `health.sh`, `fetch-model.sh` never lock and refuse to run unless `PRUEFSTAND_LOCK_HELD=1`);
processed work recorded in `state/processed.jsonl` (pr, head sha, dispatch run id, result; private branch
`executor-state`, which also holds `state/nightly_counter`); a gated PR with **no
baseline** for its `eval_fingerprint` gets `failure` "no baseline for <fp>; run baseline-promote" (never pass);
fork PRs are gated from branch `gate/pr-N` (pushed by the owner after review) only when its head SHA equals the fork
head SHA at dispatch time, and the status goes to that SHA only; the candidate never sees the held-out canary registry; baselines live on
the data root on the VM disk (`$PRUEFSTAND_DATA_ROOT/baselines/`, last 20 per fingerprint; ADR-0019) with only `index.json` in the private repo;
the candidate reaches GPU models only through the trusted `llm-proxy` (generator + embedding models only, judges blocked by its allow-list; R10 D206, ADR-0018);
the weekly backup bundle is `age`-encrypted as a whole and copied weekly to the owner's laptop as well (receipt file in
the data root, `backup-check` warns after 8 days; R11 D229); sanitised dashboard data and `heartbeat.json` (refreshed every
15 min during long jobs, D225) go to the public repo `dheena18/pruefstand-dashboard-data` (repo-scoped PAT kept in
the private repo; no private-repo token in the public repo); the dashboard itself is served by **GitHub Pages**
(R11 D235). An infra failure during a run (Ollama, tunnel, data root) posts `error`, never `failure`, and retries once
after `health.sh --repair` (D226); after a second infra failure it is recorded as processed with result `error`
and runs again only on a new owner dispatch ("…; re-dispatch to retry", R12 D274, R13 D288). Night window 22:00–06:00
Europe/Berlin; nightly = refusal stratum + block *k* of `full` (`pruefstand run --split full --stratum all --block auto`,
k = `state/nightly_counter` mod 3, incremented only after a completed nightly, R13 D298/D299), gated against baseline
ref `nightly-b<k>`, drift against the release anchor `release-b<k>` of the same block (R13 D305); the hosted guard
gates the job by its `run` output, a job starting after the fired night's 06:00 ends at once with
`infra_error="window_exceeded"` (R13 D290), a phase that would end after 06:00 stops the same way, a skipped nightly
is reported, never silent (R12 N1, N4.3; D248–D251, D256); cause-switches weekly (D223). PR runs gate against ref
`main`; with `--judged-subset` (the PR default since D655: a PR run needs a 20 % margin, i.e. at most 72 of the 90 min) the 150-case subset limits generation **and**
judging of the `core` answerable cases, security cases always run in full (D199, R13 D295).

## 3. Tooling (exact commands) — the single definition of Make targets

Development environment: the **TrueNAS VM** `pruefstand-exec` (Ubuntu 24.04) through VS Code Remote-SSH (R10 Z7);
optional alternatives: WSL2 Ubuntu 24.04, Linux, macOS (all commands are POSIX). Clone into the Linux filesystem
(`~/code/pruefstand`; on WSL never under `/mnt/c`); `git config core.autocrlf input`;
all files are LF (`.gitattributes`: `* text=auto eol=lf`).
Prerequisites (T0.0, each with a verify command): git, make, jq, uv, Python 3.12 (`uv python install`),
Node 22 LTS (fnm) + pnpm (`corepack enable`), Docker (+ Compose, user in `docker` group), gh (HTTPS; on the VM with the public-repo-only fine-grained token, §1 rule 9).
GitHub Models credential outside Actions = `PRUEFSTAND_GH_MODELS_TOKEN`, never `GITHUB_TOKEN` (D333); never export `.env` wholesale into a shell that runs `gh` (an exported `GITHUB_TOKEN`/`GH_TOKEN` overrides gh's stored login → 404 on `actions/runs`); if one is set, use `env -u GITHUB_TOKEN -u GH_TOKEN gh …`.

| Target | Runs |
| --- | --- |
| `make install` | `uv sync --all-packages --all-extras` and `pnpm -C apps/dashboard install` (dashboard part once it exists) |
| `make check` | `lint typecheck arch file-size coverage` — what CI runs on every PR |
| `make lint` | `ruff check .` and `ruff format --check .` |
| `make format` | `ruff format .` and `ruff check --fix .` |
| `make typecheck` | `mypy --strict` **once per import root** (a loop over the root list below; R12 N6.3, D266; exact recipe in coding-standards §1.1) |
| `make arch` | `lint-imports` (import-linter contracts, ADR-0016) |
| `make file-size` | fails on any source file > 300 lines |
| `make test` | `pytest -m "not integration and not e2e and not live and not gpu and not slow and not network"` plus `--doctest-modules packages/pruefstand/src` (D128) (pytest `--import-mode=importlib`; **one** root list used for both pytest `pythonpath` and mypy `mypy_path` (R9 X4.2): `packages/pruefstand/src`, `apps/rag-demo/src`, `packages/pruefstand/tests`, `apps/rag-demo/tests`, `scripts`, `data`, `experiments`, `tools`, `action`, `infra/gpu`, `benchmarks`, `infra/vm`, `infra/cluster`, `infra/gate-executor/orchestrator`, `infra/gate-executor/llm-proxy` (R11 D232) — exact TOML in `docs/engineering/coding-standards.md` §1.1; mypy `explicit_package_bases`; env `LITELLM_LOCAL_MODEL_COST_MAP=True`) |
| `make coverage` | the `make test` set (incl. doctests) with `--cov`, then `scripts/check_coverage.py` (the gate is defined once, in §6) |
| `make test-e2e` | `pytest -m e2e`: full pipeline against the **real** stack (`docker compose --profile live`: Qdrant + rag-demo + llama.cpp + embeddings) |
| `make test-live` | `pytest -m live`: real model calls (llama.cpp container; GitHub Models when `PRUEFSTAND_GH_MODELS_TOKEN` (Models: read) is set, D333) |
| `make cassettes` | re-records `tests/cassettes/` from **real** model calls (needs the `live` stack) |
| `make test-integration` | `pytest -m integration` (Docker needed) |
| `make test-slow` | `pytest -m slow` (PR: reduced simulation grid, 500 sims; nightly sets `PRUEFSTAND_SIM_GRID=full` for 4 000 sims, D131) |
| `make test-gpu` | `pytest -m gpu` (on the VM, against the A40 Ollama server through the tunnel; run it as `pruefstand-lock make test-gpu`, R11 D212) |
| `make schemas` | `pruefstand schema export --out schemas/` + OpenAPI export |
| `make schemas-fresh` | regenerates schemas and fails if `git diff` is non-empty (CI) |
| `make ui-check` | dashboard lint, typecheck, unit, Playwright (from T8.1/T8.3) |
| `make docs` | `mkdocs build --strict` |
| `make experiments` | reproduces all RQ tables/figures into `results/` (from T7.4) |
| `make clean` | removes build, cache and coverage files |
| Local stack | **On the VM prefer `make up PROFILES="core live dev"`** (mk/docker.mk exports the offset ports). A raw `docker compose …` is allowed only after `make ports-env` has written the offset ports into your VM `.env`, verified by `make check-ports`: compose has no arithmetic, so without that a raw call binds the executor's default ports (R13 D310, superseding D278). A stack session (up → Done-when checks → down) holds `stack.lock` from up to down (A13-M8). Profiles: `core` (Qdrant); `--profile live` adds rag-demo + llama.cpp + CPU embeddings (tier 1); `--profile gpu` (VM only) adds `rerank-cpu` and Qdrant on `$PRUEFSTAND_HOME/qdrant`; the GPU models run in Ollama on the cluster, never in compose (R10). **On the VM, owner and agents add `--profile dev` with `PORT_OFFSET=10000`** (Qdrant 16333/16334, rerank 18201, rag-demo 18000) so they never clash with the executor stack on the default ports (R11 D214); Done-when checks against internal-only services use `docker compose exec` or these dev ports, never `localhost` of the executor stack (D233) |

There is no `PYTEST_ARGS` / `PLAYWRIGHT_ARGS` passthrough: to run a subset, call `uv run pytest -m <marker> <path>`
or `pnpm exec playwright test <spec>` directly.

Python 3.12, `uv` only (no pip/poetry). Node 22 LTS, `pnpm` only. Targets are created by T0.1 (all of
them, working, even if they find nothing to run yet); later tasks add files and may append new task-specific targets (e.g. `gpu-up`), but never redefine a §3 target — except `ui-check` (filled by T8.1, extended by T8.3) and `experiments` (filled by T7.4), whose T0.1 stubs these tasks replace.
Shared files edited by many tasks (`Makefile`, root `pyproject.toml`, `.gitignore`, `.env.example`,
`DATA_LICENSES.md`, `.importlinter`, and the dependency lists in `packages/*/pyproject.toml` /
`apps/*/pyproject.toml`) are **append-only**: add your lines in the task's last commit. `uv.lock` is never
hand-merged: after rebasing, take `main`'s version and re-run `uv lock`. Also shared and edited only as your own section/hunk in the last commit (then rebase): `scripts/models/record_cassettes.sh`,
`.github/workflows/live-e2e.yml`, `packages/pruefstand/src/pruefstand/cli/__init__.py` (+ `cli/stubs.py`),
`examples/live/pruefstand.yaml` and `docker-compose.yml` (D140). New task
Make targets go into their own `mk/<area>.mk` (the root `Makefile` does `-include mk/*.mk`, T0.1).

## 4. Architecture rules (enforced by import-linter)

Layers in `pruefstand`, top may import bottom, never the reverse:

```text
cli                           (incl. the top-level `pruefstand.mcp` server, T10.1)
pipeline                      (orchestration / use cases; the only place that combines ingest + attacks)
report | gate | runner | dataset
metrics
judges | adapters | store | ingest | perturb | attacks
llm
core                          (all shared models, configs, protocols, errors, ids, hashing, logging)
                              — imports nothing internal
```

Modules in the same row never import each other. All shared types live in `core`
(`docs/architecture/interfaces.md`, "Where types live").

- `gate` is **pure**: numbers in, decision out. No I/O, no LLM, no clock, no randomness without an
  explicit `numpy.random.Generator` argument.
- `gate` never imports `metrics`; metric direction is passed in (`ScoreTable.higher_is_better`).
- `metrics/deterministic` never calls an LLM. `metrics/judged` only via `judges`.
- Every LLM call goes through `pruefstand.llm.LLMClient`. `litellm` is imported only in
  `pruefstand.llm.backends.litellm`; direct `litellm`/`openai`/`anthropic` imports anywhere else fail CI.
- `apps/rag-demo` must not import `pruefstand`, and nothing under `apps/` may read `datasets/`.
- The dashboard never computes metrics; it renders `run.json` / `gate.json`.

## 5. Code rules

- Type hints everywhere; `mypy --strict` clean; no `Any` in public signatures; no `# type: ignore`
  without an error code and a reason.
- Pydantic v2 models (`frozen=True`, `extra="forbid"`) for every structure crossing a module boundary.
- One responsibility per module; files ≤ 300 lines, functions ≤ 50 lines; cyclomatic complexity ≤ 10
  (ruff `C901`).
- No print (ruff `T20`; CLI scripts under `scripts/`, `tools/`, `experiments/`, `benchmarks/`, `data/` are exempt);
  use `pruefstand.core.logging.get_logger(__name__)` (structlog, JSON in CI).
- Lint config is `docs/engineering/coding-standards.md` §1.1 verbatim (D127): `max-args = 8`,
  `max-positional-args = 5`; signatures fixed in `interfaces.md` win: those that exceed a limit carry an inline
  `# noqa: <code>` and must appear in the "Allowed long signatures" table of coding-standards §1.1 (R9 X4.1); any
  other `noqa` for these codes is a review blocker.
- Errors: raise subclasses of `pruefstand.core.errors.PruefstandError`; never bare `except:`;
  never swallow exceptions; external calls have timeouts.
- All prompts live in versioned text files (`*_v<N>.txt`) next to the code that uses them; never
  inline prompt strings. Changing a prompt = new version file.
- Seeds: every random operation takes a seed or a `numpy.random.Generator`. No global random state.
- Config only via typed settings (`pydantic-settings`); secrets only from env vars, never in files,
  logs, run artefacts or exceptions. **Every** secret and environment variable (name, location, creator,
  scope, first task, rotation) is listed once in `docs/ops/secrets.md`; the committed template is `.env.example`
  (sections LOCAL / VM-SHARED / VM-EXECUTOR / CLUSTER; executor values only in `/home/pruefstand/runner.env`, R11 D213). GitHub App keys and PATs are repo/environment secrets, never `.env`. A task that
  adds a variable adds its row there and its line in `.env.example`.
- Public functions/classes have docstrings (Google style) stating inputs, outputs, raises.
- German test strings are UTF-8 literals (`"Kündigung"`), never escaped.
- No new dependency without adding it to the ADR/decision log with a reason; prefer stdlib.
- **Free providers only**: Ollama on the A40 cluster (provider `ollama`, ids `ollama/<tag>`, via the VM tunnels; always
  the native `/api/chat` / `/api/embed` API, LiteLLM `ollama_chat` inside `llm/backends/litellm.py` only, per-model
  `options` from `infra/gpu/models.yaml`; R11 D219–D221; R12 D252: `num_ctx` is fixed per model, sampling options are
  catalogue defaults within `option_bounds`, `llm-proxy` enforces only `num_ctx`, `keep_alive` and the allow-list), llama.cpp (CPU),
  GitHub Models free tier. `LLMPolicyConfig`
  allows nothing else unless listed (opt-in free tiers: Mistral, Gemini, Groq, OpenRouter `:free`); paid
  providers need `allow_paid: true` (off). Private docs, canaries and held-out data are **never** sent to an
  external provider; `LLMPolicy` enforces this. No hosted generator anywhere (D126).
- **Qwen3 thinking is always disabled** (`enable_thinking=false` on llama.cpp / Ollama `"think": false`) in every tier and role; the flag
  is part of the config hash (D95).

## 6. Testing rules

- Coverage gate (**the single definition**, D130; other docs point here): measured by `make coverage` on the
  unit marker set incl. doctests, `src` only (tests, scripts and generated code excluded); **≥ 90 %** for each
  of `pruefstand/{core,gate,metrics,perturb}`; **≥ 80 %** overall, computed separately for `pruefstand` and for
  `rag_demo` by `scripts/check_coverage.py`. Dashboard `src/lib` ≥ 80 % via `vitest --coverage` in `make ui-check`.
  No ratchet file; CI fails below.
- **No fakes for models or the target** (ADR-0008, real-stack testing). There is no FakeLLM and no
  FakeTarget. What is allowed:
  - pure-function unit tests on **real inputs** (real law text, real questions, real configs); no network,
    no Docker, no GPU, < 1 s each;
  - statistical validation of `gate.stats` on simulated numbers (tests the maths, not the product);
  - **cassettes**: responses recorded from **real** model calls by `make cassettes`, committed under
    `tests/cassettes/`, re-recorded weekly; used only for fast parser/retry/plumbing tests of code that calls a real model or the real
    target: `llm/`, `judges/`, `metrics/judged/`, `dataset/`, `perturb/`, scripts that call models (T2.6), the
    pipeline's recorded target exchanges (`tests/cassettes/target/`, T1.10) and rag-demo's own HTTP clients
    (generator, embeddings, reranker; T1.13, T3.4–T3.6) (e.g. `tests/cassettes/judged/`). Every
    behaviour a cassette covers also has a `live` test. Never hand-write a cassette.
- Failures in e2e tests come from the real rag-demo **bug switches** in `apps/rag-demo/configs/rag*.yaml` (`tenant_filter:
  post_topk`, `shared_public_merge: unfiltered`, `reranker: off`, prompt variants, `answer_language: en`).
- Property tests (Hypothesis) for stats, perturbations, normalisers, hashing.
- Every bug fix starts with a failing regression test.
- Markers: `integration` (Docker), `e2e` (full pipeline on the real `live` stack), `live` (real model
  calls), `gpu` (A40 Ollama via the VM tunnels), `slow` (> 10 s), `network`, `quarantine` (`@pytest.mark.quarantine(issue=N)`, R9).
  The tier-1 `live` job selects `-m "live and not e2e and not gpu and not network"` (R9 D9-16).
- CI tiers (`docs/engineering/ci-cd.md`): **tier 0** code checks (hosted, every PR); **tier 1 live**
  (`live-e2e.yml`, hosted CPU runner: real Qdrant + rag-demo + ≤ 2B llama.cpp generator (thinking off) +
  embeddings, no reranker, split `smoke_live` (20 cases), ≤ 20 min, `timeout-minutes: 30`; real PR comment;
  every same-repo PR, main, nightly). The tier-1 gate **decides on hard fails and the `error_rate` absolute check
  only** (R9 X5.6); language / citation / refusal-phrase results are **reported** (`tier1_deterministic_only`) and
  the `injection_success` check is reported, not gating (n = 2; R9 X3.11; injection gates in tier 2); paired
  statistics are never gated at n = 20. Tier-1 baselines are two artefacts (R9 X1.4): `live-baseline` (written
  only by push-to-main runs of the 20-case `smoke_live` PR shape) and `live-baseline-nightly` (nightly 40-case
  runs); PRs compare only to `live-baseline`.
  Judged metrics are informational: as many cases as fit in 10 GitHub Models **calls** per PR, cached; no quota →
  `judge_mode=skipped`; no CPU judge (D94–D97). The bug-switch scenario matrix runs nightly and on PRs touching
  `apps/rag-demo/**`, one job per scenario, deterministic outcomes only (D98). **Tier 2 full** (private executor
  on the A40s: core + robust_pr, trusted PRs, main, nightly) holds the statistical gate and the statistical scenarios.
- Committed configs under `examples/**` and `apps/**/configs/**` keep `gate.min_clusters ≥ 30`
  (`test_committed_configs.py`); test-only configs live in `packages/pruefstand/tests/fixtures/configs/` and may
  lower it (R9 X1.5).
- In prompts, every "Done when" line that needs more than a laptop is tagged: `[GPU]` (A40 cluster, run from the VM),
  `[NET]` (internet), `[DOCKER]`, `[HUMAN]` (a person must act or judge). Untagged lines run offline.
- Snapshot tests (syrupy) for PR comment and report rendering.
- Statistical code must have a worked numeric example in its docstring (a doctest, run by `make test`, D128)
  and a simulation test (PR: 500 sims, bound α + 4·SE; nightly: 4 000 sims, D131).
- `docs/engineering/test-matrix.md` lists every public symbol with its owning task and test, **one row per owner**
  (R13 D296). Statuses: `covered` (the owning prompt contains the concrete test), `planned` (specified, owning task
  not yet merged; informational, never blocks another task's merge), `weak`. A task keeps **its own** rows current and
  finishes only when they are `covered` (D133); another task's `planned` row never blocks it. A task that deletes a module moves or replaces
  that module's tests in the same PR (no test imports a deleted module, D132).

## 7. Git, PRs and CI

- Branch: `<type>/<task-id>-<slug>` e.g. `feat/T1.6-gate-stats` (type from the prompt header). Never commit
  to `main` — the only exception is T0.1, which lands on `main` by direct push before protection exists.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `ci:`, `chore:`), scope = module.
- One task per PR, ideally < 400 changed lines excluding tests/fixtures. Larger → split.
- PR description uses `.github/pull_request_template.md` (task ID, evidence, interface changes,
  follow-ups, checklist).
- Bootstrap exception: T0.1–T0.4 run before branch protection exists (switched on in T0.5); use local
  `make check` and `git diff main...HEAD`.
- Binding round-9 decisions are D146–D195 in `docs/decisions.md` (source: `docs/planning/reviews/round9-resolution.md`);
  binding round-10 decisions are D196–D210 (source: `docs/planning/reviews/round10-resolution.md`, Z1–Z7);
  binding round-11 decisions are D211–D247 (source: `docs/planning/reviews/round11-resolution.md`, Y1–Y7; D242–D247 from `round11-integration.md`);
  binding round-12 decisions are D248–D283 (source: `docs/planning/reviews/round12-resolution.md`, N1–N7, plus the reviewers' exact minor fixes in `round12-{dev,ai,ui,arch}.md`; D284–D286 from `round12-integration.md`);
  binding round-13 decisions are D287–D323 (D319–D323: round-13 integration) (source: `docs/planning/reviews/round13-resolution.md`, P1–P5, plus the reviewers' exact minor fixes in `round13-{dev,ai,ui,arch}.md`).
  D324–D327 (2026-10-31, owner-verified cluster facts, `docs/ops/setup-log.md`) implement ADR-0018: one Ollama server for both GPUs, port 11434 only, ngrok rejected.
  D328–D332 (2026-10-31, owner decision, setup log §6–§7) implement ADR-0019: models on the cluster's own disk, one judge
  `gemma3:12b` for PR and nightly, no local datagen model (public text via GitHub Models, private docs/canaries via the
  local judge model), data root a plain directory on the VM disk, cluster scripts copied over SSH.
- Several agents in parallel: follow `tasks/PARALLEL-PLAN.md` (one task = one worktree = one PR; shared files
  only as your own hunk in the last commit; GPU steps under `pruefstand-lock` (`/var/lib/pruefstand/gpu.lock`),
  compose stacks under `stack.lock`; each worktree gets `.env` copied or symlinked by the lead agent, never committed,
  R11 D234).
- CI must be green; no `--no-verify`, no skipping hooks, no disabling tests, no lowering coverage gates.
- Workflows: no `pull_request_target` in the public repo, with **one documented exception** (R9 X2.2):
  `.github/workflows/gate-router.yml` (posts `pruefstand/gate` = success "not gated" when no gated path changed,
  `pending` "gated: awaiting tier-2 dispatch" otherwise; **no checkout** of any ref, `GITHUB_TOKEN` permission
  `pull-requests: read` only, changed files read from the API; the status is posted with a `pruefstand-bot` App token
  minted from the key in environment `gate-router`, deployment branch `main` only; R13 P1.1, D287). The T0.2
  workflow guard allowlists exactly that file and asserts it has no checkout step. No self-hosted runner in the
  public repo; every `uses:` SHA-pinned.
- Solo-maintainer flow: PRs are required, **0 required approvals**; required checks are listed in
  `docs/engineering/ci-cd.md` (incl. `pruefstand/gate`, **pinned** to the App `pruefstand-bot`, D287). The maintainer
  merges.
- Every PR gets an AI review with `prompts/_review.md` in a fresh session **and** a second review from a
  different model family via GitHub Models (`gh models run <model> < review-input.md`). Copilot code
  review is optional (not part of GitHub Pro). Findings are fixed or answered before merge.

## 8. Docker and deployment

- Every service has a multi-stage Dockerfile, non-root user, pinned base image digest, `HEALTHCHECK`,
  and is listed in `docker-compose.yml` under a profile.
- Images are built and scanned (Trivy) in CI; `hadolint` clean.
- No secrets in images or compose files; use `.env` (git-ignored) + `.env.example` (committed); names and
  locations: `docs/ops/secrets.md`.

## 9. Data and licensing

- Never commit raw corpora or model weights. Download scripts pin versions and SHA-256 checksums.
  `scripts/check_no_raw_data.py` (in `make check`, T2.1) fails on tracked data files (`*.parquet`, `*.jsonl`
  dumps, …) except under the allowlist (R9 X1.3): `results/**`, `experiments/**/results/**`,
  `apps/dashboard/fixtures/**`, `datasets/fixtures/**`, `tests/**/fixtures/**` (the last pattern matches a `tests/`
  path segment anywhere, e.g. `packages/pruefstand/tests/fixtures/runs/`). MEMERAG-derived files stay banned
  everywhere. Nothing else may be added to the allowlist without a decision row.
- GermanQuAD/GermanDPR-derived data is CC BY 4.0 (HF cards, checked 2026-10-28; GermanRAG verified in
  T2.1); OLDP-derived is ODbL; keep them in separate dataset configs. MEMERAG (CC BY-NC 4.0) is
  download-only: never redistributed, never used for training. Update `DATA_LICENSES.md` when adding a source.
- Canary tokens and synthetic private docs are test data; never use real personal data.

## 10. Definition of Done (every task)

- [ ] All "Done when" items pass, evidence pasted in the PR (`[GPU]`/`[NET]`/`[DOCKER]`/`[HUMAN]`
      items: evidence from the environment named by the tag, or the named person's sign-off)
- [ ] `make check` green locally and in CI
- [ ] Tests written first; coverage gates hold (§6)
- [ ] `docs/engineering/test-matrix.md` rows for my symbols are `covered` (D133)
- [ ] Docs updated: module README/docstrings, affected diagrams, `docs/decisions.md`
- [ ] No TODOs without a linked follow-up task ID
- [ ] Reviewed with `prompts/_review.md`; review findings resolved
