# Round 11 integration log

Scope: reconcile the pack after the six fixers applied `round11-resolution.md`, plus seven binding
integration decisions from the lead. New decision rows **D242–D247** in `docs/decisions.md`
(D215 marked superseded; D206, D208, D226, D230, D235, D239 annotated).

## 1. Decisions applied

| # | Decision | D-row | Files |
| --- | --- | --- | --- |
| 1 | `llm-proxy` networking replaces the host-network design: tunnel binds 11434/11435 on `127.0.0.1` **and** `172.17.0.1`; `llm-proxy` = normal container on `gate-net` + non-internal bridge `proxy-egress` (`10.231.0.0/24`, created by T0.7), upstream `LLM_PROXY_UPSTREAM=http://172.17.0.1:11434`; candidates only on `gate-net`, `LLM_PROXY_URL=http://llm-proxy:11500`, no host-gateway entry; VM nftables rule: tunnel ports on `172.17.0.1` only from `proxy-egress`; dev proxy on its compose network + `proxy-egress`, `127.0.0.1:21500` | D242 (supersedes D215) | interfaces §1.5, docker.md §3, security.md (C16 row, candidate row, D4), ci-cd §7, deployment.md (table, diagrams, rejected placements), overview, sequences, gpu-cluster §1/§6, runbook §0/§1, T0.7 (Context, S5, new S5b `setup-proxy-net.sh` + `nftables-pruefstand.nft`, vm_check `proxy-net`/`firewall`/tunnel binds, tests, Done-when), T6.2a (Context, sandbox, S4b, S6, S9, tests, Done-when, Depends text), T3.2/T3.4/T3.6, T0.3, `.env.example` (+`LLM_PROXY_UPSTREAM`), secrets.md, CLAUDE.md, SPEC, ADR-0005, ADR-0012, REVIEW.md, TASKS (T0.7, T6.2a), prompts/README, test-matrix (+VM proxy-net row) |
| 2 | Pages: single writer `docs.yml`, one artefact; dashboard at site root `https://<GH_OWNER>.github.io/pruefstand/` (`basePath` `/pruefstand`), docs at `/pruefstand/docs/`; T8.5's `deploy.yml` builds artefact `dashboard-site` and dispatches `docs.yml` with `dashboard_run_id`; `docs.yml` downloads it only by run id (plain `main` push: newest successful `deploy.yml` run; else placeholder) | D243 | ui-spec §2.1/§14.3, T8.5 (Goal/Context/Subtasks/Files/Tests/Done/Docs rewritten), T0.4 (Pages layout, `site_url`, `workflow_dispatch`, deploy job, new S6c `assemble_pages_site.sh` + test), T8.1 (`basePath` `/pruefstand`, no top-level `docs/`), T9.2 URLs, ADR-0011, ADR-0017, ADR-0012, ci-cd (`docs.yml`/`deploy.yml` rows, §2.5 diagram, §3), deployment.md, release.md, runbook §9, secrets.md (Pages row, `NEXT_BASE_PATH`), `.env.example` (`NEXT_BASE_PATH`), test-matrix (smoke row, new assembly row), TASKS (T0.4, T8.5) |
| 3 | Demo: leak-probe pass in `deploy.yml` → `release-demo-ready` uploads artefact `demo-ready`; private `demo-nightly.yml` (06:15 Berlin, T8.5) jobs `demo-deploy` → `demo-e2e`; `cloudflared` container on `demo-net` with `CLOUDFLARE_TUNNEL_TOKEN` from `/home/pruefstand/demo.env`; no `demo`/`preview` environment | D244 | T8.5, T8.4 (schedule line, compose note, hop rule), ui-spec §4.6/§14.2/§14.3, ci-cd (§1.1 deploy row, new §1.2 `demo-nightly.yml` row, demo jobs removed from `nightly.yml` row, §2.3/§2.5 diagrams, §3), ADR-0012, ADR-0017, security.md (D4, data-repo row), secrets.md (`CLOUDFLARE_TUNNEL_TOKEN`), `.env.example`, runbook §9 (token no longer in `runner.env`), deployment.md, sequences, release.md, T0.5 S13 (Vercel/Fly/`demo`/`preview` setup removed), test-matrix (leak-probe row), TASKS T8.5 |
| 4 | `RunManifest.infra_error: str \| None` (`"<kind>: <detail>"`), only with `stop_reason="aborted"`; written by the executor via new `ArtifactStore.mark_aborted` (T1.8); `counts["infra_error"]` removed | D245 | interfaces §1.5/§2/§7/§8/§10, data-model (ER + `runs` table), SPEC §6.2, ADR-0013, T1.1 (field, validator, tests), T1.8 (store method, test), T6.2a, T6.3, test-matrix |
| 5 | `legal_hard` order: day `--pass answer` → datagen weekend `--pass review` → offline `--pass build`; `is_drift(..., *, a0=None)` added to interfaces §6 | D246 | D230 annotated, T5.3 Context, SPEC §7.5 row, TASKS T5.3, PARALLEL-PLAN, prompts/README; interfaces §6, T5.4 (no longer "pre-approved"), test-matrix `is_drift` row |
| 6 | `RERANK_URL=http://rerank-cpu:8201` (container port 8201); `health.sh` exit 15 in interfaces §1.5; owner cluster commands only via `sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster <op>`; `make` exports every `*_PORT` | D247 | interfaces §1.5, docker.md (row + compose snippet `RERANK_PORT`, default `${RERANK_HOST_PORT:-8201}:8201`), deployment diagram, T3.1a (port, exit 15 wording, prompt step), runbook (§ header, §2, §2a uses `$C <op>` = wrapper, health exit 10–16), gpu-cluster (owner row, stop row), T0.7, T6.2a drills, T3.1b, `.env.example` + secrets.md (`*_PORT` row, `COMPOSE_PROJECT_NAME`) |
| 7 | Prompt "Depends on" = TASKS "Depends" (script check) | – | TASKS: T3.2, T3.4, T5.1, T8.4 + T0.7; T8.5 + T0.7, T6.2a. Prompts: T3.5, T3.6, T5.2a "via" mentions reworded without task IDs. Script result: 0 mismatches over all prompts |

## 2. Stale-term sweep (item 7)

| Term | Result |
| --- | --- |
| `network_mode: host` for `llm-proxy` | none left except D215 (superseded row) and the rejected-placement note; `network_mode: host` remains only for the dev `rag-demo-dev` (T3.2) and CI quickstart, which are not `llm-proxy` |
| `host.docker.internal` / `host-gateway` | only in negative statements ("no host-gateway entry") and D215 |
| `Vercel`, `Fly` | only "dropped" statements, alternatives tables and negative tests; T0.5 S13 rewritten (was a live Vercel/Fly/`demo`/`preview` setup step) |
| `headers.json` | only negative build checks (T8.1, T8.5, ui-spec §7.4) |
| `/dashboard/` path | none (T9.2, T8.1, T8.5, ui-spec, test-matrix fixed) |
| `:8000` for rerank | none (docker.md, deployment.md fixed) |
| `tmux` for Ollama start | only superseded rows (D196, D200), rejected placements, T0.6 informational check and "never tmux" rules |
| `hosted_vllm`, `vLLM` as default | only history/"replaces" mentions; `docs/engineering/README.md` "vLLM flags" fixed |
| `TEI` outside tier-1 CPU embeddings | only the TEI **wire format** of `rerank-cpu` (`/rerank` contract) and rejected-alternative rows; kept intentionally |
| `counts["infra_error"]` | none outside D245's text |

## 3. Checks

- `tasks/TASKS.md` vs prompt "Depends on": 0 mismatches (script in the integrator's scratchpad).
- test-matrix totals unchanged in shape: covered 245, open 13, weak 1 = 259 (two new rows added as covered,
  matching the previous header that already counted 245/259).
- No encoding damage (scan for mojibake over all `.md` and `.env.example`).

## 4. Left for owners / notes

- `10.231.0.0/24` is a fixed default for `proxy-egress`; T0.7 refuses to create it if it clashes with a VM
  route and records any change in `decisions.md`.
- `proxy-egress` is non-internal, so the trusted `llm-proxy` has internet egress (residual, security.md C16).
- The demo leak probes run on a hosted runner inside public `deploy.yml` (as ADR-0012/ci-cd already said);
  T8.5's earlier private-runner probe variant was dropped.
