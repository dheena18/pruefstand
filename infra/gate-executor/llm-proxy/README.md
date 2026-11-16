# llm-proxy

The candidate's only route to the one Ollama server (T6.2a S4b; D206, D242, D252, ADR-0018; contract:
`docs/architecture/interfaces.md` §1.5). Trusted, stdlib only, built on the VM from the private executor checkout.

- `llm_proxy_policy.py`: pure rules (allow-list, bearer key, option policy, reload detection).
- `llm_proxy_json.py`: strict JSON reading (D1070): no duplicate or case/NFKC-colliding keys, no NaN, exact
  top-level keys per route, ASCII-only output.
- `llm_proxy.py`: bounded threaded HTTP server (30 s client timeout, 32 connections, D1072); no env proxy, no redirects (D1073); `GET /api/tags` answered from the policy (D1071); `0.0.0.0:11500` inside the container; upstream only
  `LLM_PROXY_UPSTREAM` (default `http://172.17.0.1:11434`); `GET /health` →
  `{"model_reloads", "upstream_errors", "requests"}`; logs method and path only.

Environment (rows in `docs/ops/secrets.md`): `PRUEFSTAND_CANDIDATE_API_KEY` (required), `LLM_PROXY_POLICY` (JSON
`{tag: {"role", "options", "option_bounds"}}` for the run's generator + embedding tags, written by the orchestrator
from `infra/gpu/models.yaml`; a judge tag refuses to start), `LLM_PROXY_UPSTREAM`.

Thinking is always off (CLAUDE.md §5, D95): `POST /api/chat` is forwarded with `think: false` whatever the
candidate sends, absent included (D1076); `/api/embed` is unchanged.

Option policy: `num_ctx` = catalogue value; `keep_alive` and every other load-time or unknown key dropped;
`temperature`, `top_p`, `num_predict` pass inside the catalogue `option_bounds` (else 403
`option out of bounds: <key>`); `seed` passes when it is an integer; missing keys get the catalogue default; a key
without bounds keeps the default (D1060).

Tests: `uv run pytest infra/gate-executor/llm-proxy/tests -q` (pure policy on the real catalogue, the server against
a local recording upstream, static compose/Dockerfile checks). The live checks from a candidate container are T6.2a's
`[GPU] [DOCKER]` Done-when items.
