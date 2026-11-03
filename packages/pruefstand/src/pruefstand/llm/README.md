# pruefstand.llm

Every model call goes through `LLMClient` (interfaces §3). `litellm` and `openai` are imported only in
`backends/litellm.py` (import-linter contract `llm-gateway`).

| Module | Role |
| --- | --- |
| `client.py` | policy -> cache -> quota/budget -> retries -> backend -> recorder; `complete_json` with one repair call |
| `backends/litellm.py`, `kwargs.py`, `versions.py`, `limits.py` | the real calls; pure request building; provider version probes; size-capped transport |
| `providers.py` | `endpoints.yaml` / `models.yaml` lookups (A40 base URL, per-model options), read at use time |
| `retry.py` | `RetryPolicy`, `backoff_delay`, `RateLimitedError` |
| `cache_epochs.py` | per-judge cache epochs and `judge_drift.json` (not `judge_epoch`) |
| `policy.py` | provider allow-list, paid block, external-provider data guard |
| `factory.py` | `build_backend` (every prefix), `build_client` |
| `costs.py`, `costs.yaml`, `quotas.yaml` | 0.0 USD prices, GPU seconds, GitHub Models free-tier limits |
| `families.py` | `family_of`, `validate_family_plan` (table: `core/data/model_families.yaml`) |

Rules worth knowing: the catalogue (`infra/gpu/models.yaml`) decides model ids, digests and Ollama options, nothing
here names a model; `ollama/<tag>` goes to `/api/chat` with the catalogue options and `think: false`; only
`temperature == 0` calls are cached; an external provider's exhausted quota raises `QuotaExhausted` and the runner
turns it into `judge_mode=skipped`; the data guard also applies to the fallback provider.
