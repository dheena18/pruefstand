# Docker

Binding summary: `CLAUDE.md` §8. This file holds the **single port table** (§3); `deployment.md`,
`overview.md` and `gpu-cluster.md` point here.

## 1. Images

| Image | Dockerfile | Base (pinned by digest) | Purpose | Published |
| --- | --- | --- | --- | --- |
| `pruefstand-action` | `action/Dockerfile` (from the T0.3 template `infra/docker/python-uv.Dockerfile`, `PKG=pruefstand`) | `python:3.12-slim-bookworm` | GitHub Docker action entrypoint (runs the `pruefstand` CLI) | GHCR (+ Marketplace via tag) |
| `rag-demo` | `apps/rag-demo/Dockerfile` (T0.3 template) | `python:3.12-slim-bookworm` | reference RAG app (system under test) | GHCR, **public package** (D107; set once after the first `push-sign` run, T6.2b) |
| `pruefstand-smoke` | `infra/docker/python-uv.Dockerfile` | `python:3.12-slim-bookworm` | template smoke image (`make image-smoke`, T0.3) | no |
| `dashboard` (dev only) | `apps/dashboard/Dockerfile` | `node:22-bookworm-slim` | local preview of the static export served by `nginx-unprivileged` | no (GitHub Pages in production, Y7.1) |
| `rerank-cpu` | `infra/gpu/rerank/Dockerfile` (T3.1a; CLAUDE.md §8 rules) | `python:3.12-slim-bookworm` | `BAAI/bge-reranker-v2-m3` on the VM CPU (sentence-transformers), TEI-compatible `POST /rerank` | no (built on the VM) |
| `llm-proxy` | `infra/gate-executor/llm-proxy/Dockerfile` (T6.2a) | `python:3.12-slim-bookworm` | trusted allowlisting proxy from `gate-net` to the one Ollama server, generator + embed tags only (D206, ADR-0018, `ci-cd.md` §7) | no (built on the VM) |
| third-party | – | `qdrant/qdrant`, `ghcr.io/ggml-org/llama.cpp:server` (CPU), `ghcr.io/huggingface/text-embeddings-inference` (CPU tag; tier 1 and demo only) | vector DB, CPU LLM serving, CPU embeddings | pinned in compose |

**No container on the GPU cluster** (round 10 Z1, D196): GPU models are served by two plain Ollama
processes started detached (`setsid nohup`, Y5.4) on `cairo-s101lp` (`gpu-cluster.md` §4), not by an image. vLLM and GPU TEI images
are **not used** (no Docker on the cluster; rejected, D198, ADR-0009).

There is no separate `pruefstand` CLI image: users install the package from PyPI or use the Action
image. The executor runner is **not** an image: it is the official actions-runner release (pinned
version + sha256) installed on the VM `pruefstand-exec` under `/home/pruefstand/pruefstand/runner` and run
as the persistent system service `pruefstand-runner.service` as user `pruefstand` (`gpu-cluster.md` §1, §7);
it starts Qdrant, `rerank-cpu`, `llm-proxy` and the candidate containers with the VM's **rootful** Docker
daemon (Y1.3; group `docker` = `pruefstand` + the owner user only, `security.md` C18).

Exact tags and digests are recorded in `docs/decisions.md` ("Pinned versions"). Dependabot updates them
(R9-28): ecosystem `docker` for `/infra/docker`, `/apps/rag-demo` and `/action` (Dockerfiles), and
`docker-compose` for `/` (`docker-compose.yml`) and `/infra/gpu` (`compose.gpu.yml`, VM services only). T0.2 verifies
Dependabot's compose support against its current docs; if compose files are not supported, their digests
are **updated by hand per release** (release checklist).

## 2. Multi-stage template (Python services)

`infra/docker/python-uv.Dockerfile` (T0.3) is the one template; the Action and rag-demo images are built
from it (T1.12, T1.13) with their own build args. Build context = repository root. It uses plain Dockerfile
syntax only (no BuildKit-only features), so it also builds on the VM, whose Docker has no buildx.

| Build arg | Default | Meaning |
| --- | --- | --- |
| `PKG` | `pruefstand` | uv workspace member installed with `uv sync --frozen --no-dev --no-editable --package $PKG` |
| `ENTRYPOINT_BIN` | `pruefstand` | console script (or command line, e.g. `uvicorn rag_demo.api:app --host 0.0.0.0`) run by the entrypoint; arguments of `docker run` are appended |
| `HEALTHCHECK_CMD` | `NONE` | shell command that exits 0 when healthy; `NONE` = no service to probe (CLI/Action images) |
| `GIT_SHA` | `unknown` | label `org.opencontainers.image.revision` and env `GIT_SHA` (PR head SHA in CI, X2.4) |

Stages: `base` (`python:3.12-slim-bookworm@sha256:...`), `builder` (uv from `ghcr.io/astral-sh/uv:<ver>@sha256:...`,
venv in `/app/.venv`), `runtime` (venv only, `USER 10001`, OCI labels). Base and uv digests are in
`decisions.md` ("Pinned versions"); hadolint (`.hadolint.yaml`, threshold `warning`) and Trivy gate them in
`build-images.yml`. Smoke test: `make image-smoke && docker run --rm pruefstand-smoke --help`. The sketch below
shows the shape with a service healthcheck (rag-demo, T1.13):

```dockerfile
FROM python:3.12-slim-bookworm@sha256:<digest> AS base
FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:<version>@sha256:<digest> /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps apps
RUN uv sync --frozen --no-dev --no-editable --package rag-demo

FROM base AS runtime
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.source="https://github.com/dheena18/pruefstand" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 GIT_SHA=${GIT_SHA}
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2).status==200 else 1)"]
ENTRYPOINT ["uvicorn", "rag_demo.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Rules:
- Non-root user, no secrets, no build tools in the runtime stage, `.dockerignore` excludes `datasets/`, `runs/`, `data/raw/`, `.env*`.
- `GIT_SHA` is baked in so `/v1/info` can report it. For PR images it is the PR **head SHA**:
  `build-images.yml` checks out `github.event.pull_request.head.sha`, never the merge commit (X2.4).
  `/v1/info.serving` holds only static fields (engine, engine_version, quantization, GPU model, model file
  sha256; tier 2: `engine = ollama`, `model_sha256` = Ollama manifest digest); runtime counters go to `/v1/health` (X3.13). The image digest is passed at run time (`IMAGE_DIGEST` env), because an image cannot know its own digest.
- The HEALTHCHECK uses Python's stdlib because there is no curl in slim images.

## 3. Compose profiles (`docker-compose.yml`) and the port table

Sources: T0.3 (`core`, `live`, `dev`), T1.13 (`embed`, `rag-demo` in `live`), T3.1a (`gpu`: `rerank-cpu`
in the included file `infra/gpu/compose.gpu.yml` and `qdrant` with VM storage; the root file only
`include:`s it), T6.2a (`llm-proxy`, started by the orchestrator; listed in the port table), T8.5 (`demo`). `docker-compose.yml` is a shared file (own hunk, last commit, rebase; D140).

| Profile | Services | Use |
| --- | --- | --- |
| `core` | `qdrant` | unit/integration dev, indexing |
| `live` | `qdrant`, `llm` (llama.cpp CPU generator), `embed` (TEI CPU), `rag-demo` | tier-1 CI (`live-e2e.yml`, `action-selftest.yml`) and local live/e2e tests; the same real CPU stack everywhere |
| `dev` | `rag-demo` (built from source, `--reload`), `llm-proxy` (dev instance); use together with `core`, `live` or `gpu` | owner/agent development on the VM (or a laptop); on the VM always with `PORT_OFFSET=10000` (Y1.4) |
| `gpu` | `qdrant` (root file, storage `$PRUEFSTAND_HOME/qdrant` on the VM disk), `rerank-cpu` (from `infra/gpu/compose.gpu.yml`) | **VM only** (tier 2: the executor stack as user `pruefstand`, and the owner's dev stack with the `dev` ports); the executor attaches both to `gate-net`. The GPU models are Ollama on the cluster (no compose service; day/night modes are Ollama loads and unloads, no datagen mode since ADR-0019, `gpu-cluster.md` §2) |
| `demo` | `qdrant`, `llm` (llama.cpp CPU), `embed` (CPU), `rag-demo` with `apps/rag-demo/configs/rag.public.yaml`, budget + rate-limit env | optional demo on the VM (`--internal` `demo-net`, 4 vCPU / 8 GB limits, `cloudflared` sidecar on `demo-net` + `demo-egress`, P2.2; ADR-0012, D92, Y7.5) |

There is **no** CPU judge service (`llm-judge-cpu` was removed with the tier-1 CPU fallback judge, D97)
and no `ollama` service in compose: Ollama runs only on the cluster, outside Docker. The former
`gpu-night` and `gpu-large` profiles and the `vllm-*`, `tei-embed` and `tei-rerank` services are removed
(round 10).
Tier-2 VM services (`rerank-cpu`, `llm-proxy`) are added by T3.1a and T6.2a; GPU serving is Ollama on the cluster (`gpu-cluster.md`), never a compose service.

**Port table (single source).** Every host port binds to `127.0.0.1` (no exception; the only non-loopback
listener on the VM is the `autossh` tunnel's second bind on the Docker bridge gateway `172.17.0.1`, firewalled
to the `proxy-egress` subnet, D242; rules in `DOCKER-USER` and in the own `PRUEFSTAND-INPUT` chain hooked from
`INPUT`, because container → `172.17.0.1` traffic hits `INPUT`, not `DOCKER-USER`; both applied by the oneshot
`pruefstand-firewall.service`, never by flushing the ruleset, N4.2, D285). Container ports in brackets are what other containers use on the same
network (on the VM: `gate-net`).

**Two stacks on the VM (Y1.4).** The **executor** stack (user `pruefstand`, `compose.executor.yml`, T6.2a)
uses the default ports. The owner/agent **dev** stack uses compose profile `dev` with `PORT_OFFSET=10000`
in the owner's `.env`. Compose has no arithmetic, so `make` (T0.3) exports the per-service host-port
variables (`QDRANT_HTTP_PORT=$((6333+PORT_OFFSET))`, `QDRANT_GRPC_PORT`, `RERANK_HOST_PORT`,
`RAG_DEMO_HOST_PORT`, `LLM_PROXY_PORT`; each = default + `PORT_OFFSET`) and the compose files use
`${QDRANT_HTTP_PORT:-6333}` etc. (`.env.example` sets only `PORT_OFFSET`; `docs/ops/secrets.md` lists every
exported name). Because raw `docker compose` never sees what `make` exports, **`make ports-env`** writes
the effective values once, literally, into the owner's VM `.env` (`QDRANT_HTTP_PORT=16333`, …), so a plain
`docker compose --profile core|live up` binds the dev ports as well (prefer `make up PROFILES="…"`; raw compose
only after `make ports-env`, verified by `make check-ports`; A13-M6, D310); **`make check-ports`** (and a `vm_check` warning) flags any container of the
`pruefstand-dev` project bound to a default port (R12 A12-M4). Both
stacks can run at the same time; Done-when checks against internal-only services use
`docker compose exec` or the dev ports, never the executor's `localhost` ports (Y6.5).

| Service | Profile(s) | Image | Host port (container); executor / laptop / CI | Dev host port on the VM (`PORT_OFFSET=10000`) | Volumes | Healthcheck |
| --- | --- | --- | --- | --- | --- | --- |
| `qdrant` | `core`, `live`, `demo`, `gpu` | `qdrant/qdrant:<ver>@<digest>` | `6333` (6333), `6334` (6334, gRPC) | `16333`, `16334` | `qdrant_data:/qdrant/storage` (VM, profile `gpu`: bind mount `$PRUEFSTAND_HOME/qdrant` on the **local VM disk**, never in the data root) | `GET /readyz` |
| `llm` | `live`, `demo` | `ghcr.io/ggml-org/llama.cpp:server@<digest>` (CPU) | `8080` (8080) | `18080` | `${LIVE_MODEL_DIR:-${HOME}/.cache/pruefstand/models}:/models:ro` | `GET /health` |
| `embed` | `live`, `demo` | `ghcr.io/huggingface/text-embeddings-inference:cpu-<ver>@<digest>` | `8090` (80) | `18090` | model cache `:ro` | `GET /health` |
| `rag-demo` | `live`, `dev`, `demo` | `ghcr.io/dheena18/rag-demo@sha256:<d>` or build | `8000` (8000); the executor's **candidate** has no host port (`gate-net` only) | `18000` | `./corpus:/corpus:ro`; `RAG_CONFIG` env selects `apps/rag-demo/configs/rag*.yaml` (`rag.yaml` tier 1 / CPU, `rag.gpu.yaml` tier 2 / A40, X3.15; `rag.public.yaml` demo, T8.4); never a canary-registry mount (X2.5) | `GET /v1/health` |
| `rerank-cpu` | `gpu` (VM) | `rerank-cpu` (built on the VM, base pinned by digest) | executor: **none** (`gate-net` only, container port **8201**, no auth, Y2.2) | `18201` (8201) | `rerank-models:/models` (HF weights of the pinned revision, VM disk) | `GET /health` |
| `llm-proxy` | executor: started by the orchestrator (T6.2a); `dev` | `llm-proxy` (built on the VM) | executor: **none** (normal container on `gate-net` + `proxy-egress`, container port **11500**; candidates use `LLM_PROXY_URL=http://llm-proxy:11500`, D242) | `127.0.0.1:21500` (11500; dev instance on its compose network + `proxy-egress`) | none (upstream `LLM_PROXY_UPSTREAM=http://172.17.0.1:11434` via `proxy-egress`) | `GET /health` |
| tunnel to the one Ollama server (no compose; ADR-0018) | – | system unit `pruefstand-tunnel.service` (user `pruefstand`; `127.0.0.1` forward already set up, `docs/ops/setup-log.md` §3; `172.17.0.1` added by T0.7) | `11434` on `127.0.0.1` and `172.17.0.1` → cluster `127.0.0.1:11434`; `172.17.0.1` only from the `proxy-egress` subnet (VM firewall, D242) | shared (same tunnel) | – | `GET /api/tags` |
| T0.6 tunnel check (temporary, only where no tunnel exists) | – | `ssh -N -L …` in `tunnel_check.sh` | `21434` (Y1.4; closed after the check) | – | – | – |
| dashboard (no compose) | – | `pnpm dev` | `3000` | `13000` | – | – |

The candidate reaches `rerank-cpu` inside `gate-net` (`RERANK_URL=http://rerank-cpu:8201`); the dev stack
uses `http://localhost:18201` from the host. The TEI-compatible `/rerank` contract is unchanged.
**`llm-proxy` networking (D242, supersedes the host-network design of Y1.5/D215).** The `autossh` tunnel
(T0.7) binds `11434` (the only Ollama port, ADR-0018) on `127.0.0.1` **and** on the Docker bridge gateway `172.17.0.1`. `llm-proxy` is
a normal container attached to the internal network `gate-net` **and** the small non-internal bridge
`proxy-egress` (subnet `10.231.0.0/24`, created by T0.7, `external: true` in compose); it reaches Ollama at
`http://172.17.0.1:11434` over `proxy-egress` and forwards only the native Ollama API (`/api/chat`,
`/api/embed`, `/api/tags`, Y3.1). Candidates are only on `gate-net` and reach `http://llm-proxy:11500` by
name; no container has an `extra_hosts`/`host-gateway` entry. The VM firewall (`DOCKER-USER` + `PRUEFSTAND-INPUT`, D285)
accepts `172.17.0.1:11434` only from the `proxy-egress` subnet, so neither `gate-net`, `demo-net` nor the LAN reaches the tunnel. The
dev instance (`dev` profile) joins its compose network and `proxy-egress` and publishes
`127.0.0.1:${LLM_PROXY_PORT:-11500}:11500` (`21500` on the VM). The candidate's client is the same as
against Ollama directly plus the bearer key (Y2.1). Env names:
`RERANK_URL`, `LLM_PROXY_URL`, `LLM_PROXY_UPSTREAM`, `PRUEFSTAND_CANDIDATE_API_KEY`, `GPU_LOCK_TIMEOUT_S`
(`docs/ops/secrets.md`). Ports `8100`–`8103` and `8200` (former vLLM/TEI GPU services) are retired and
are not reused. The host firewall of the VM (T0.7) allows nothing inbound except SSH.

**Demo networking (round 13 P2.2, optional, T8.4/T8.5).** The demo app containers (`rag-demo`, `qdrant`,
`llm`, `embed` of compose project `pruefstand-demo`) sit only on the **`--internal`** network `demo-net` (`10.232.0.0/24`), so
they have no egress at all. `cloudflared` (`10.232.0.2`) is attached to `demo-net` **and** to the egress network
**`demo-egress`** (`10.233.0.0/24`, created by `setup-proxy-net.sh` like `proxy-egress`, `external: true`); it is
the only demo container that reaches the internet (outbound to Cloudflare). `pruefstand-firewall.sh` adds
`DOCKER-USER` rules that drop traffic from `demo-egress` to `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
(`demo-net` needs none: it is `--internal`), and `PRUEFSTAND-INPUT` drops both subnets → the VM's own addresses
and host ports. So no demo container
reaches the LAN, the TrueNAS host (NFS/SMB/web UI), `cairo-s101lp:22`, `gate-net` or the tunnel ports (`security.md` D4).

`depends_on` uses `condition: service_healthy`. Config comes from `.env` (git-ignored) with
`.env.example` committed (every name: `docs/ops/secrets.md`). Every service has `restart: unless-stopped` (except in CI), `mem_limit` and
log rotation (`max-size: 10m`). On the VM the executor attaches `qdrant` and `rerank-cpu` to the
`--internal` network `gate-net` for the candidate, together with `llm-proxy`; the candidate reaches
`llm-proxy` only at `http://llm-proxy:11500`; nothing on `gate-net` reaches the tunnel (`:11434`),
and `llm-proxy` (the only container on `proxy-egress`) is the only path to Ollama, for the generator and embedding tags only.

### 3.1 VM services of profile `gpu` (`infra/gpu/compose.gpu.yml`, T3.1a)

```yaml
  rerank-cpu:
    profiles: ["gpu"]
    build: {context: infra/gpu/rerank}        # python:3.12-slim-bookworm@sha256:<digest>, non-root
    environment:
      RERANK_MODEL: BAAI/bge-reranker-v2-m3
      RERANK_REVISION: <40-hex revision>       # pinned in infra/gpu/models.yaml (server: vm)
      OMP_NUM_THREADS: "4"
      RERANK_PORT: "8201"                      # container port; RERANK_URL=http://rerank-cpu:8201 (D247)
    ports: ["127.0.0.1:${RERANK_HOST_PORT:-8201}:8201"]   # dev stack only (make exports 18201 on the VM); compose.executor.yml resets ports (Y2.2)
    volumes: ["rerank-models:/models"]
    mem_limit: 6g                              # CPU models on the VM ≤ 24 GB in total (D202)
    read_only: true
    healthcheck: {test: ["CMD", "python", "-c", "<urllib GET /health>"], interval: 10s}
```

**No GPU reservation exists anywhere in compose**: the VM has no GPU, and the cluster runs no Docker.
GPU placement is Ollama's: one server with `CUDA_VISIBLE_DEVICES=0,1` on port `11434` and `OLLAMA_MODELS=/data/dheena/Models` on the cluster disk (ADR-0019)
(the existing server is reused, else started by `infra/cluster/start-ollama.sh`; `gpu-cluster.md` §4, ADR-0018);
`health.sh` checks via `/api/ps` that each model is fully on a card. The candidate rag-demo in a gate job gets a
read-only root fs, `--cap-drop ALL` and only the `--internal` network `gate-net` (no internet egress),
see `ci-cd.md` §7.

The model allocation per mode (day/night/datagen), VRAM numbers and Ollama settings are defined only in
`gpu-cluster.md`.

## 4. Tagging and signing

| Tag | When |
| --- | --- |
| `sha-<12>` | every `main` build |
| `main` | latest `main` build |
| `sha-<head sha>` (PR) | built by `build-images.yml` on a hosted runner from the PR **head SHA** (X2.4) for same-repo branches (incl. `gate/pr-N` copies of fork PR heads, D104), pushed by digest and cosign-signed (origin only), `pruefstand/image` posted on that SHA; the executor pulls only by digest, without credentials (public package), and checks the image revision label |
| `vX.Y.Z`, `vX.Y`, `vX` | release |

Deployments and the Action reference **digests**, never mutable tags (the tagged `action/action.yml`
uses `:vX.Y.Z`; its digest is in the release notes). Release images are signed with cosign keyless
(OIDC) and carry an SPDX SBOM (syft) plus a provenance attestation. You can verify one with:

```bash
# released images: identity pinned to the release workflow at the exact tag
cosign verify ghcr.io/dheena18/rag-demo@sha256:<digest> \
  --certificate-identity https://github.com/dheena18/pruefstand/.github/workflows/release.yml@refs/tags/vX.Y.Z \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
# PR images (executor): identity regexp build-images.yml@refs/(heads/.+|pull/N/merge), exact form in ci-cd.md §7
```

## 5. Scanning

| Tool | Where | Fails on |
| --- | --- | --- |
| hadolint | `build-images.yml`, pre-commit | any warning (rule exceptions inline with a reason) |
| Trivy image scan | `build-images.yml`, `release.yml` | HIGH/CRITICAL with a fix available; SARIF uploaded to code scanning |
| Trivy config scan | `build-images.yml` | misconfiguration in Dockerfiles/compose (root user, no healthcheck) |
| `docker compose config -q` | `build-images.yml` | invalid compose for any profile |
| Dockle (optional) | nightly | CIS best-practice violations |
