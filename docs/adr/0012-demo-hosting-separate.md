# 0012 — Dashboard on GitHub Pages; optional demo on the VM behind a Cloudflare Tunnel, separate from the GPU cluster

- Status: Accepted (revised 2026-10-28: free only, CPU generator on the demo host; revised 2026-10-31, round 8: minimum host size, JSON error body, pre-deploy leak probes; round 9: leak-probe job owned by T8.5 (X2.8), daily data refresh; **revised round 11 (Y7.1, Y7.5; D235, D239): dashboard on GitHub Pages, Vercel dropped; the optional demo runs on the VM behind a free Cloudflare Tunnel, Fly.io/Hetzner dropped**; revised round 13 (P2.2, P5.3–P5.5, UI13-06/-08/-11; D291, D302–D304): `--internal` `demo-net` + `demo-egress` with an RFC 1918 drop, demo-ready marked by the separate `demo-ready.yml` as release asset `demo-ready.json`, `deploy.yml` dashboard-only, one-call lookup, pin and kill switch by dispatch)
- Date: 2026-10-27
- Tasks: T8.4, T8.5

## Context
The public "Try it" page is an open LLM endpoint. People can run up costs on it, target it with prompt
injection, and they expect it to stay up. The A40 cluster is a research resource with no public ingress,
and it must not be exposed. Round 11: the project uses free services only, the static dashboard needs no
server, and the VM has spare CPU for one small demo instance, so no paid host is needed.

## Decision
- Dashboard: **GitHub Pages** (static export; CSP only as hash-based `<meta>`, no header files), published
  by `docs.yml`, the single Pages writer (dashboard at the site root `/pruefstand/`, docs at `/pruefstand/docs/`;
  ADR-0017, D243).
- Demo API (optional, T8.4): the rag-demo image on the **executor VM** `pruefstand-exec`, reachable from the
  internet only through a free **Cloudflare Tunnel** (`cloudflared`, outbound only; no inbound port, no
  host port). It runs as user `pruefstand` on its own **`--internal`** Docker network `demo-net` (never `gate-net` or `proxy-egress`, no
  host-gateway entry, firewalled from the tunnel ports on `172.17.0.1` (D242), no data-root or home mount); only
  `cloudflared` (`10.232.0.2`) is also on the egress network `demo-egress` (`10.233.0.0/24`), `DOCKER-USER` drops
  `demo-egress` → `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and `PRUEFSTAND-INPUT` drops both subnets → the
  VM's own addresses (round 13 P2.2, `security.md` D4) with its own Qdrant (demo corpus snapshot), CPU embeddings and
  llama.cpp, limited to **4 vCPU / 8 GB** (`cpus`, `mem_limit`) inside the VM CPU-model budget (≤ 24 GB
  in total). T8.4's `abuse_test.py` records p95 latency and RSS with these limits. The demo pulls only
  release digests marked **demo-ready** by the separate public workflow `demo-ready.yml` (`workflow_run` of
  `release.yml`; its job `release-demo-ready` uploads the release asset **`demo-ready.json`** after clean leak
  probes); `demo-deploy` makes **one** anonymous API call per night (`releases/latest`) and downloads
  `demo-ready.json` and `image-digests.json` via `browser_download_url` (release assets do not expire; no
  artefact download, no token; round 12 N5.3/A12-M9, round 13 P5.3),
  pulls the **public GHCR image by digest**, verifies it with cosign, and is updated only by the private nightly job `demo-deploy` (workflow `demo-nightly.yml`,
  D244; dispatch inputs `mode` = `deploy` | `pin` | `unpin` | `disable` | `enable` and `tag`); `cloudflared` runs as a container on `demo-net` + `demo-egress` with `CLOUDFLARE_TUNNEL_TOKEN` from
  `/home/pruefstand/demo.env`; there is no `demo` or `preview` GitHub environment. Queries use a CPU dense encoder, the reranker is off (as in tier 1), and the generator is a **small German-capable
  model served by llama.cpp on the same CPU host** (the tier-1 model, ADR-0008), called through rag-demo's own
  OpenAI-compatible client (rag-demo never imports `pruefstand`). No external LLM API, no cost.
- Controls:
  - an in-app daily request budget (exceeded → friendly 503) that also protects the CPU host;
  - every error is a JSON body `{code, message, retry_after_s}` (D138), so the page never relies on reading
    the `Retry-After` header;
  - a kill switch: `demo-nightly.yml` dispatch `mode: disable` creates a flag file inside the container, so the
    API answers 503 `demo_disabled` at once without a restart (`mode: enable` removes it; `DEMO_ENABLED` needs a
    restart and is not the kill switch); demo rollback = `mode: pin` (previous digest for 14 days);
  - a per-IP rate limit of 10 requests per minute and 100 per day (11th request in a minute → 429), kept
    **in-process** (client IP from `CF-Connecting-IP`), so a container restart resets it;
  - questions limited to 500 characters;
  - a fixed tenant list and no write endpoints;
  - question text is kept in logs for at most 7 days.
- The cluster is never reachable from the internet.
- The demo page shows the attribution and the ODbL notice for OLDP-derived text (DATA_LICENSES.md §4.6).
- The demo index uses only the public canary set; held-out canaries never leave the private executor repo.
- `demo-ready.yml` job `pre-deploy-leak-probes` (owned by **T8.5**, X2.8) runs the leak probes (attack
  split) against the demo candidate (release image with `apps/rag-demo/configs/rag.public.yaml`, public
  canaries only); only a clean run marks the digest demo-ready (`release-demo-ready` `needs:` it and uploads
  `demo-ready.json`; with no `demo-ready.json` on the latest release `demo-deploy` keeps the deployed digest
  and exits 0). A demo-path failure fails only `demo-ready.yml`, never a dashboard refresh (UI13-06).
- `deploy.yml` is **dashboard-only** (`push: main`, daily cron, `data_sha` dispatch): it rebuilds the dashboard
  artefact with the newest sanitised data, and `docs.yml` publishes it on `workflow_run` (no dispatch);
  every build writes `build-id.txt` = `<head_sha>-<deploy_run_id>`, which the post-deploy smoke waits for
  (P5.5). A data-caused dashboard regression is rolled back with `data_sha`, a code-caused one with a revert PR.
- **Try-it e2e (Y7.5):** job `demo-e2e` of `demo-nightly.yml`, after `demo-deploy`, runs nightly on the VM
  against the one demo instance; test groups run
  sequentially, the container is restarted between groups, and before each combination the limits are reset
  from inside the container (`docker compose exec rag-demo-e2e curl -X POST localhost:8000/v1/_test/reset`,
  P5.4), so the loopback check is real.
- The demo never touches the executor's lock, Qdrant, `llm-proxy`, tunnels or GPU; if the VM is busy or
  down, the demo is slow or down (the page says so), and gate runs take priority (the demo has fixed
  CPU/RAM limits).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Serve from the A40s through a tunnel | Exposes the research cluster, and the demo would go down whenever experiments run |
| Vercel (dashboard) + Fly.io/Hetzner (demo) (round-10 design) | Accounts, tokens and possibly cost; Vercel needs header files the static export cannot deliver cleanly (round 11 UI11-05) |
| Demo on the VM with an open inbound port | Exposes the trusted executor host; the Cloudflare Tunnel is outbound-only |
| Serverless GPU | Cold starts and cost |
| No live demo | Weaker portfolio; a recorded GIF stays as the fallback |

## Consequences
- Positive: zero hosting and API cost; no deploy credentials in the public repo; abuse is bounded by the
  rate limit and the daily request budget.
- Negative: the small CPU model answers worse and slower than the cluster generator. The page says so.
- Negative: a public endpoint now lives on the trusted executor VM; contained by `demo-net`, the
  outbound-only tunnel, the RFC 1918 egress drop and resource limits (`security.md` D4). GitHub Pages has no preview deployments.
