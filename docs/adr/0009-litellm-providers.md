# 0009 — All LLM calls via LiteLLM; provider set; judge ≠ generator family

- Status: Accepted (revised 2026-10-28: free providers only, external-provider data guard; revised 2026-10-31: round 8 family plan, no hosted generator, no CPU judge; round 9 judge pass rule, reviewer roles, input cap, weekend datagen; revised round 10 (D198, D204, D209): all tier-2 serving is Ollama, provider `ollama` replaces `hosted_vllm`, vLLM and TEI rejected; revised round 11 (D219–D221, D224): native Ollama API only, catalogue options enforced, fallback judge informational)
- Amended by: [ADR-0018](0018-single-ollama-server.md) (2026-10-31: one Ollama server for both GPUs, port 11434 only)
- Amended by: [ADR-0019](0019-local-model-storage-small-disk.md) (2026-10-31: one judge `gemma3:12b`, public-text datagen on GitHub Models, private-doc datagen on the local judge model, models on the cluster disk)
- Amended by: T5.1 addendum below (D520-D527: retries, quota exhaustion, cache epochs)
- Amended by: T5.2a addendum below (D700: schema-guided JSON, `complete_json_meta`)
- Date: 2026-10-27
- Tasks: T1.2, T1.4, T1.13, T3.1a, T3.1b, T5.1

## Context
The generator, the judges, data generation and the LLM perturbations all use different models, some local
and some hosted. Cost and token logging, caching and budgets have to work the same way for all of them.
A judge from the generator's own model family grades that family's style favourably.
Round 10 (owner facts 2026-10-31) found that the A40 cluster has Ollama installed (with the
`qwen3.8:27b-q8_0` generator already pulled) but no confirmed Docker or vLLM, a nearly full local disk
and no systemd linger, so the planned vLLM + TEI containers cannot run there.

## Decision
- `pruefstand.llm.LLMClient` is the only entry point. `LiteLLMBackend` (`pruefstand.llm.backends.litellm`) is the only
  module that imports `litellm`, enforced by ADR-0016.
- Providers:

| Provider | LiteLLM prefix | Use |
| --- | --- | --- |
| **Ollama on the A40s** (one server on `:11434` for both GPUs, ADR-0018, reached from the VM through the `autossh` tunnel) | `ollama/<tag>` in configs and the catalogue (D209, D221); `LiteLLMBackend` translates it to LiteLLM's native `ollama_chat/<tag>` (`/api/chat`, `/api/embed`; D219), never Ollama's `/v1/*`; base URL from `infra/gpu/endpoints.yaml`: `OLLAMA_GPU0_URL` / `OLLAMA_GPU1_URL` (both the same server, ADR-0018) | generator `qwen3.8:27b-q8_0` (Ollama family `qwen35` → `qwen`, `think: false`, pinned digest `8f5fb6b7…1766039`) and `bge-m3` embeddings (generator lane), the one judge `gemma3:12b` for PR and nightly (judge lane; also writes synthetic private docs, canaries and held-out data locally, role `DATAGEN`; ADR-0019); models on the cluster's own disk `$CLUSTER_DATA_ROOT/Models` |
| CPU reranker on the VM (`rerank-cpu`, sentence-transformers, TEI-compatible `POST /rerank`) | – (not an LLM; called by rag-demo through `RERANK_URL`) | `BAAI/bge-reranker-v2-m3`, tier 2 only |
| llama.cpp server on CPU (OpenAI-compatible) | `openai/` + local `api_base` | tier-1 live CI generator (called by rag-demo's own client); laptops |
| GitHub Models (free tier, rate-limited) | `github/` | tier-1 **informational** judge via `PRUEFSTAND_GH_MODELS_TOKEN` (`models: read`; in Actions `PRUEFSTAND_GH_MODELS_TOKEN: ${{ github.token }}`, D333; ≤ 10 calls/PR, ≤ 60/nightly), **public-text datagen** (T4.2 questions/references, T4.5 rewrites, T5.3 `legal_hard` review; ADR-0019), RQ2 large free-tier judges, cross-check samples of public items |
| Optional free tiers, opt-in per config: Mistral "Experiment", Google Gemini free tier, Groq free tier, OpenRouter `:free` | their LiteLLM prefixes | extra RQ2 judges only |

- **Free only (owner decision 2026-10-28).** `budget.max_usd_per_run = 0`. `LLMClient` refuses any
  provider not in `allowed_providers` (default `openai_compatible_local`, `ollama`, `github`; D209) and
  any paid provider unless `allow_paid: true` (off; no paid API is planned).
- **External-provider data guard.** Free tiers may train on inputs. Private documents, canaries
  (public and held-out) and private-executor data are never sent to a provider outside the A40s /
  local CPU (`ollama` and `openai_compatible_local` count as local). `LLMClient` blocks a request to an external provider when its `prompt_id` belongs to the
  `datagen.private_docs` family or its text contains a registered canary (`CanaryRegistry`), and logs
  the block (no content). Only public law text and public test cases may go to external providers.
- On HTTP 429 / exhausted quota from GitHub Models the tier-1 run skips judging and records
  `judge_mode=skipped` (ADR-0008). There is no CPU fallback judge.
- **No hosted generator.** rag-demo never calls an external provider: its generator endpoints must
  resolve to the executor's internal network or localhost (T3.2 test), because retrieved chunks carry
  tenant documents and canaries. A hosted generator would need `allow_paid` and the data guard, both off.
- **Family plan** (SPEC §6.3, `core/data/model_families.yaml`): generator `qwen` (all tiers; all
  `role: generator` catalogue entries share it); **one** A40 judge `gemma` (`gemma3:12b`, PR and
  nightly, the other card than the generator; ADR-0019); public-text datagen = a pinned GitHub Models family ≠ `qwen`,
  ≠ `gemma` (T4.2); private docs, canaries and held-out data = the local judge model (never external); tier-1
  informational judge a GitHub Models model of a non-`qwen` family. `core/data/model_families.yaml` maps Ollama
  family `qwen35` → `qwen`, `gemma3` → `gemma`. `test_catalogue.py` checks that no judge entry
  has the generator family and that no default-profile model has a non-commercial licence.
- **Qwen3 thinking** is disabled for every Qwen call in every tier (`enable_thinking=false` /
  `/no_think` on llama.cpp; on Ollama `"think": false` on native `/api/chat`; D204, D219);
  `LLMClient` applies it to any Qwen call in any role.
- **Ollama serving rules** (`gpu-cluster.md` §2.1; round 11 Y3, AI11-01). Only the **native** API
  is used: Ollama ignores `options` (incl. `num_ctx`) on its OpenAI-compatible `/v1` routes and falls
  back to a short server default, which silently truncates prompts (**verify** on the pinned
  version). Each model has fixed `options` in `infra/gpu/models.yaml` (`num_ctx`, `num_predict`,
  `temperature`, `seed`, `top_p`): generator `num_ctx` **8192**, the one judge `gemma3:12b` **12288** = generator 8 192 +
  rubric/answer allowance ≤ 3 072 + 1 024 output reserve (round 13, D306; T3.1b may lower it only if its VRAM
  measurement fails; if it does not fit at 4 slots, lower
  `OLLAMA_NUM_PARALLEL` (server-wide, ADR-0018) to 2 before `num_ctx`, AI12-09), judges `num_predict` 384. Preload
  (`switch-mode.sh`, `health.sh`) sends exactly these options, because a request with different
  options reloads the model; `llm-proxy` enforces only `num_ctx` and `keep_alive` (the load-time
  options) plus the model allow-list, strips other load-time keys, and passes `temperature`, `seed`,
  `top_p`, `num_predict` through within the catalogue `option_bounds` (outside → 403; round 12 N2, refines D220; catalogue values
  are defaults, not overrides), so a candidate cannot reload, offload or resize the shared generator,
  while M17 and the T6.3 churn runs really change sampling. Server env (one server, ADR-0018) `CUDA_VISIBLE_DEVICES=0,1`, `OLLAMA_NUM_PARALLEL=4`,
  `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_KEEP_ALIVE=24h` (mode switches manage residency), `OLLAMA_NOPRUNE=1`
  (**verify**), `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MODELS=$CLUSTER_DATA_ROOT/Models` (the
  cluster's own disk, ADR-0019), `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_CONTEXT_LENGTH=8192` as a default only (the
  catalogue `num_ctx` on every request is the control); source of record: the owner's `~/start-ollama.sh`.
  Models are pinned by tag **and manifest digest** (tags are mutable). Embeddings: `bge-m3` via
  `/api/embed` (dense only; ADR-0010). Evidence, not request bodies: `test-gpu` checks
  `prompt_eval_count` on a 7 000-token prompt, and a model reload during a run (`load_duration` > 1 s
  after preflight) aborts it as an infrastructure failure (SPEC §6.2, D226).

- Every call uses temperature 0 and a seed where the provider supports it, and is logged to `llm_calls.parquet`
  (model, tokens, cost, latency, cached).
- Judges are configured as `ModelRef {id, family}`. The config validator rejects any judge whose family equals
  `generator_family`; at run time the same rule is checked against the generator reported by the baseline and
  candidate targets (`/v1/info.models`). There is **one** family table:
  `packages/pruefstand/src/pruefstand/core/data/model_families.yaml` (id pattern → family; core, so the config
  validator can use it); `infra/gpu/models.yaml` references families by name only. Distilled/merged models list
  their base family; an unknown model id is a `ConfigError`. A family violation always raises **`ConfigError`**:
  at load time, and at run time, where it aborts the run with `stop_reason="aborted"` (second planning review).
- T3.1b and T5.4 pin the exact models (Ollama tag + manifest digest + quantisation; HF revision SHA for `rerank-cpu`) in `infra/gpu/models.yaml` and record them in `docs/decisions.md`.
- Judges use structured output where the provider supports it: Ollama `format` with the JSON schema on `/api/chat` (`reason` `maxLength` 600, `num_predict` 384; **verify** on the pinned version), `response_format` on GitHub Models.
- **A judge gates only after passing calibration** (SPEC §7.5): κ ≥ 0.6 on the full calibration set
  **and** specificity (true-negative rate) ≥ 0.80 on the hard-negative subset with a 95 % Wilson lower
  bound ≥ 0.70; κ is never computed on a single-label subset. Otherwise its judged metrics are
  informational in every tier.
- **Judge roles in dataset review** (SPEC §3.5, ADR-0019): the one judge `gemma3:12b` reviews every split as a
  batch job in **reject-only** mode and never writes or rewrites references; rejected items are regenerated by
  the public-text datagen model (another family).
- **Judge input cap** = the judge's context window minus 1 024 tokens, counted with the judge's
  tokenizer; over-cap inputs are truncated (lowest-ranked chunks first, `details["truncated"]`), logged,
  counted (`counts["judge_truncated"]`) and listed in the report; > 5 % truncated → the metric is
  informational (`judge_truncated`).
- The judge's serving version (`"<engine> <engine_version> <quantization> <digest[:12]>"`) and
  `judge_epoch` are part of `eval_fingerprint` (ADR-0006).
- **Fallback judge** (D224): a run that uses any judge other than the configured one
  (`judge_fallback=true`) reports all judged metrics as informational and is not promoted as a judged
  baseline; verdicts of two judges are never compared.
- **Family separation** (AI11-12, ADR-0019): the gating judge's family (`gemma`) never wrote a reference it
  grades (references come from the GitHub Models datagen family); private-tenant documents are written locally
  by the judge model (they are contexts for deterministic leak checks; fallback: a small non-`qwen` local GGUF).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Provider SDKs directly | One code path per provider for logging, cost and retries |
| LangChain | Heavy, with an unstable API, for a thin need |
| Paid hosted APIs (Anthropic, OpenAI) | Owner rule: free providers only |
| vLLM (OpenAI-compatible) + TEI on the A40s (round-1 to round-9 design) | Needs Docker (or a Python env) and local model storage on the cluster; neither is available (round 10). Kept only as the optional upgrade path if the admins later provide Docker and the PR budget cannot be met |
| Ollama on a cluster network port | No authentication in Ollama; loopback + tunnel instead (`security.md` C14) |

## Consequences
- Positive: switching between local and hosted models is a config change, and budgets work the same everywhere.
- Negative: a LiteLLM version bump can change its cost tables. Pin the version, and keep our own override table
  for local models (cost 0, GPU-seconds tracked).
- Negative (round 10): GGUF quantisations (`Q8_0`, `Q4_K_M`) differ from the AWQ checkpoints planned
  before; Ollama has fewer serving knobs than vLLM (no guided-decoding backends, no Prometheus
  metrics), and parallel slots are not bit-deterministic. The first model load per mode comes from the
  cluster's own disk (ADR-0019) and is excluded from timing budgets.

## Addendum T5.1 (2026-11-03): retries, quota exhaustion, cache key and epochs

- `LLMClient` retries 429, 5xx, timeouts and connection loss with exponential backoff and seeded jitter
  (`RetryPolicy`, defaults 3 retries, 1 s base, 30 s cap), honours `Retry-After`, never retries other 4xx and
  records every attempt. A `Retry-After` above 60 s is a daily limit, not a pause.
- An external provider's 429 after the retries (or a long `Retry-After`) raises `QuotaExhausted`; the model is
  exhausted for the rest of the run and later calls fail without a network call. A configured fallback judge is
  policy-checked first (data guard, allowed providers) and answers with `fallback=True`.
- The cache key is `stable_hash(model, "<provider version>#e<epoch>", prompt id, prompt version, messages,
  temperature, max_tokens, seed, response_format)` (interfaces §8). The version is probed once per model and run
  (Ollama tag + digest, llama.cpp `/props`) or taken from the first GitHub Models response. The epoch comes from
  `cache_epochs.json` and is bumped by `invalidate_judge`; it is not `judge_epoch` and not in `eval_fingerprint`.
- Interface change: `LLMClient.__init__` gains the keyword-only `retry` and `epochs` (additive, defaults keep
  T1.4 behaviour); `build_client` and `LiteLLMBackend.resolve_version` are new.

## Addendum T5.2a (2026-11-03): schema-guided JSON and the response of a JSON call

- `LLMRequest` gains the optional `json_schema` (default None). For `ollama/` models it is sent as the native `format`
  (grammar-constrained decoding); other providers keep `json_object` mode. It is in the cache key only when set, and
  left out of `model_dump` when None, so existing cassette hashes and cache keys are unchanged.
- `LLMClient.complete_json_meta(req, schema)` returns `(object, LLMResponse)`; `complete_json` is its first element.
  The judge needs `cached` and `fallback` of the answer it parsed. The JSON-call logic lives in `llm/json_call.py`.
- Why: the judge output must stop at 600 characters of `reason` without a free-running generation (AI11-14e), and the
  benchmark showed the judge model wraps JSON in code fences without a schema (`experiments/model_selection/REPORT.md`).
- Impact: additive; D526 follow-up closed (D700).
