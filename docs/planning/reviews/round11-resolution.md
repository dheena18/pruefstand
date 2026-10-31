# Round 11 resolution — binding decisions (cold read 6)

Inputs: `round11-dev.md` (2/9/12), `round11-ai.md` (0/5/9), `round11-ui.md` (0/8/15), `round11-arch.md` (0/11/11).
Overrides earlier resolutions where they conflict. Where silent, apply the reviewer's exact fix.

## Y1 One service identity on the VM (dev blocker 2, arch majors)

| # | Decision |
| --- | --- |
| Y1.1 | A single system user **`pruefstand`** on `pruefstand-exec` owns the runner, orchestrator, cluster SSH key (`/home/pruefstand/.ssh/id_ed25519_cluster`), the `autossh` **system** unit (`pruefstand-tunnel.service`), state and the lock at `/var/lib/pruefstand/gpu.lock` (mode 0660, group `pruefstand`). |
| Y1.2 | The owner's login user is in group `pruefstand`; owner/agent commands that need the GPU use the wrapper `pruefstand-lock <cmd>` (same lock file). `MAINTENANCE` is a file `/var/lib/pruefstand/MAINTENANCE`, not a per-user env var. |
| Y1.3 | Docker on the VM is **rootful** (dedicated VM). Members of group `docker`: `pruefstand` and the owner user only. New threat-model row: coding agents run as the owner user and are root-equivalent on the VM; accepted for a dedicated VM; prompts forbid touching `/var/lib/pruefstand/**` and `/home/pruefstand/**`; secrets for the executor live only under `pruefstand`. |
| Y1.4 | Ports: the executor stack uses the default ports; the owner/agent **dev** stack uses compose profile `dev` with `PORT_OFFSET=10000` (Qdrant 16333/16334, rerank 18201, rag-demo 18000). T0.6's tunnel check uses temporary ports 21434/21435 so it never clashes with T0.7's tunnel. |
| Y1.5 | `llm-proxy` runs with `network_mode: host`, listens on the Docker bridge gateway (`172.17.0.1:11500`) and forwards to the tunnel ports on `127.0.0.1`; candidate containers reach it via `host.docker.internal:11500` (`extra_hosts: host-gateway`). |

## Y2 Auth and API (dev blocker 1)

| # | Decision |
| --- | --- |
| Y2.1 | rag-demo sends `Authorization: Bearer $PRUEFSTAND_CANDIDATE_API_KEY` on every call to `LLM_PROXY_URL` (generator **and** embeddings). Owned by **T3.4** (embeddings client) and **T3.6** (generator client); T1.13 gets the header in its client from day 1 (empty key allowed in tier 1). |
| Y2.2 | `rerank-cpu` has **no** auth: it is reachable only on the internal candidate network, has no host port in the executor stack, and holds no secrets. secrets.md and T6.2a are corrected. |
| Y2.3 | New target API endpoint **`POST /v1/retrieve`** `{tenant_id, question, top_k}` → `{chunks}` (no generation), used by `robust_pr`. Owned by T3.5; contract in interfaces §1.1. |

## Y3 Ollama correctness (AI major)

| # | Decision |
| --- | --- |
| Y3.1 | All Ollama calls use the **native** API (`/api/chat`, `/api/embed`; LiteLLM provider `ollama_chat`), never `/v1/*`, so `num_ctx` and options apply. |
| Y3.2 | Per-model fixed `options` (`num_ctx`, `num_predict`, `temperature`, `seed`, `top_p`) live in `infra/gpu/models.yaml`; preload uses exactly these options; `llm-proxy` overwrites any client-supplied `options`/`keep_alive` with the catalogue values. |
| Y3.3 | One model id format: `ollama/<tag>` in configs and catalogue; the bare `<tag>` only in Ollama API bodies. |

## Y4 Time budgets that fit (AI + arch majors)

| # | Decision |
| --- | --- |
| Y4.1 | `robust_pr` uses `/v1/retrieve` only (no generation). |
| Y4.2 | Tier-2 reranker: rerank top **10** with passages truncated to 256 tokens, batched. T3.1b measures; if the reranker lane exceeds 20 min per PR run, `robust_pr` runs with reranker off and is documented as first-stage robustness. |
| Y4.3 | Night window **22:00–06:00 Europe/Berlin** (DST handled with two UTC cron entries + a local-time guard), budget ≤ 8 h. Nightly runs a **rotating stratified 600-case subset of `full`** (full coverage every ~3 nights); cause-switches run **weekly** (Sunday), not nightly. |
| Y4.4 | Judge fallback (any judge other than the configured one) ⇒ judged metrics are **informational** for that run; no cross-judge comparison ever. |

## Y5 Unattended operation (arch majors)

| # | Decision |
| --- | --- |
| Y5.1 | Heartbeat is refreshed every 15 min during long jobs (not only at job end), so `executor-down` never fires during a healthy nightly. |
| Y5.2 | Infra failure mid-run (Ollama down, tunnel lost, NAS unavailable) ⇒ run `stop_reason="aborted"` with `infra_error`, commit status **`error`** (not `failure`), one automatic retry after `health.sh --repair`. |
| Y5.3 | TrueNAS host reboot: VM autostarts; NAS mount is a systemd mount unit with `x-systemd.automount,nofail`; services `Requires=` the mount; preflight checks it. |
| Y5.4 | Ollama on the cluster is started detached with `setsid nohup` (not tmux) so it survives logout regardless of `KillUserProcesses`; T0.6 checks that a detached process survives logout; the VM preflight relaunches it when down. |
| Y5.5 | Backups: the NAS copy **plus** a mandatory weekly copy to the owner's laptop; `backup-check` job warns if the laptop copy is older than 8 days (laptop pushes a receipt file to the NAS). |

## Y6 Dev majors

| # | Decision |
| --- | --- |
| Y6.1 | test-matrix.md refreshed for round 10: rows for T0.7, cluster scripts, `llm-proxy`, `rerank-cpu`, `/v1/retrieve`; correct paths. |
| Y6.2 | `datagen` mode sets `MAINTENANCE` itself and is the only mode allowed while it is set. `legal_hard` (T5.3) runs in two passes like T4.5: generate in datagen mode, validate in day mode. |
| Y6.3 | `cluster.env` is generated by T3.1a from `infra/cluster/cluster.env.template` and written to NAS `bin/`. |
| Y6.4 | mypy/pytest paths include `infra/vm/**` and `infra/cluster/**` Python helpers. |
| Y6.5 | Done-when checks against internal-only services run via `docker compose exec` or the `dev` profile ports, never `localhost` of the executor stack. |
| Y6.6 | Worktrees: `_lead-agent.md` copies or symlinks `.env` into each worktree; PARALLEL-PLAN shared-file list completed. |

## Y7 UI majors

| # | Decision |
| --- | --- |
| Y7.1 | Dashboard hosting = **GitHub Pages** (free); CSP via `<meta>` only (hash-based), no header files; Vercel dropped. |
| Y7.2 | Empty fixture build: `generateStaticParams` returns one placeholder param (`_empty`) with `dynamicParams = false`, rendering the empty state. |
| Y7.3 | Fixtures F-PARTIAL, F-NO-BASELINE, F-JUDGE-SKIPPED are **derived from real tier-1 runs** by a documented script `apps/dashboard/fixtures/derive.py` (truncate run, drop baseline, set `judge_mode=skipped`), all under `apps/dashboard/fixtures/**`. |
| Y7.4 | Render functions accept `baseline: RunResults | None`; no-baseline renders the ⚪ state. Tier-1 Slices label `error_rate` as deciding. |
| Y7.5 | Demo (optional T8.4): hosted on the VM behind a free **Cloudflare Tunnel**, CPU model on the VM, rate limits in-process; the try-it e2e runs nightly on the VM against one demo instance, tests run sequentially, limits reset by restarting the container between test groups. |
| Y7.6 | testing-strategy §3.10 stale lines removed; `sequences.md:121` `;` fixed. |
