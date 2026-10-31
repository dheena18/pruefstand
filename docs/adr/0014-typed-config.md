# 0014 — Typed Pydantic config, published JSON Schema

- Status: Accepted (revised 2026-10-31: round 8; round 9 X1.5, X3.15; round 11 D220-D222)
- Date: 2026-10-27
- Tasks: T1.2, T3.2

## Context
Users write `pruefstand.yaml`, and `rag.yaml` controls the RAG app. A typo in YAML (for example `max_drp`)
silently changes behaviour. The mutations are config patches, so they need validating too.

## Decision
- `PruefstandConfig` (interfaces §15) and `RagConfig` (§16) are Pydantic v2 models with `extra="forbid"` and a `version` field.
  Cross-field validators check that the judge family differs from the generator family, that the splits exist, and that
  thresholds are in range.
- YAML is loaded with `yaml.safe_load` only.
- rag-demo has two committed profiles validated by `RagConfig`: `apps/rag-demo/configs/rag.yaml` (tier 1, CPU) and
  `apps/rag-demo/configs/rag.gpu.yaml` (tier 2, A40; the only file the executor takes from a PR).
- Committed gate configs (`examples/**`, `apps/**/configs/**`) need `min_clusters ≥ 30`; test-only configs in
  `packages/pruefstand/tests/fixtures/configs/` may lower it.
- Secrets are never in YAML. A field such as `auth_env` names an env var, and `pydantic-settings` reads the env (`PRUEFSTAND_*`).
- `pruefstand schema export` writes the JSON Schemas to `schemas/`, where they are committed. The example files carry a
  `# yaml-language-server: $schema=` header so IDEs autocomplete them.
- `config_hash = stable_hash(normalised config)`. For `RagConfig` it covers every generation knob incl.
  `chat_template_kwargs` (Qwen3 `enable_thinking: false`), so a template flag cannot change answers
  without changing `target_fingerprint`.
- Model catalogue entries carry `family` and `license`; embedding entries also `query_prefix`, `doc_prefix`,
  `max_input_tokens`. The validator checks the family plan (SPEC §6.3) and the licence allowlist.
- Ollama catalogue entries (`infra/gpu/models.yaml`) use the id format `ollama/<tag>` (the bare `<tag>` only in
  Ollama request bodies; D221) and carry fixed `options` (`num_ctx`, `num_predict`, `temperature`, `seed`,
  `top_p`; D220) plus `kv_bytes_per_token` read from `ollama show` / the load log (and `swa_window` for Gemma;
  AI11-07); the VRAM test uses these values, never an assumed architecture.
- `RagConfig` tier-2 reranker defaults: `top_n: 10`, passages truncated to 256 tokens, batched (D222).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Hydra/OmegaConf | Interpolation magic and weaker validation |
| Plain dicts | No validation |

## Consequences
- Positive: a config error fails fast with exit code 2 and a precise message.
- Negative: each new option needs a model and schema update. A CI check catches stale schemas.
