# Architecture Decision Records

One file per decision. **During planning (until T0.0 starts the repo)** ADRs are revised in place and
marked "revised <date>". After that, an accepted ADR is not edited: to change a decision, write a new
ADR that **supersedes** the old one, then set the old one's status to `Superseded by NNNN`.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-monorepo-uv-pnpm.md) | Monorepo with uv workspace + pnpm, `src/` layout | Accepted |
| [0002](0002-walking-skeleton-first.md) | Walking-skeleton-first phase order (tier-1 gate on hard fails + `error_rate`) | Accepted (revised) |
| [0003](0003-files-source-of-truth-duckdb.md) | Run artefacts are files; DuckDB index; no Postgres | Accepted (revised) |
| [0004](0004-baseline-store-git-branch.md) | Baselines as plain files in a protected branch of the private executor repo | Accepted (revised; amended by 0019) |
| [0005](0005-two-tier-ci.md) | Three-tier CI: hosted code checks, hosted live CPU gate (real models), A40 gate in a private executor repo that pulls work (runner on the TrueNAS VM, Ollama on the cluster via tunnels) | Accepted (revised) |
| [0006](0006-two-caches-fingerprints.md) | Separate target and LLM caches keyed by fingerprints (judge serving incl. model digest + `judge_epoch` in `eval_fingerprint`); trust domains; fallback judge informational | Accepted (revised) |
| [0007](0007-paired-cluster-bootstrap.md) | Paired cluster bootstrap; fail on significant and relevant drop; one Holm family over all gated pairs | Accepted (revised) |
| [0008](0008-real-stack-testing.md) | Real-stack testing: real models, real target, real CI; tier-1 gate on hard fails + `error_rate`, everything else reported | Accepted (revised) |
| [0009](0009-litellm-providers.md) | All LLM calls via LiteLLM; provider set (Ollama on the A40s, native API only, catalogue options enforced); family plan; no hosted generator | Accepted (revised; amended by 0019) |
| [0010](0010-qdrant-hybrid-tenant-filter.md) | Qdrant only, dense (`bge-m3` via Ollama) + own German sparse, in-query tenant filter; reranker on the VM CPU (top 10 × 256 tokens, own budget lane) | Accepted (revised; amended by 0019) |
| [0011](0011-dashboard-static-nextjs.md) | Dashboard = Next.js static export over run artefacts on GitHub Pages; one build per fixture set | Accepted (revised) |
| [0012](0012-demo-hosting-separate.md) | Demo hosting separate from GPU cluster | Accepted |
| [0013](0013-observability.md) | structlog + OpenTelemetry; judge health, serving health (`model_reloads`, `infra_error`) and executor heartbeat | Accepted (revised) |
| [0014](0014-typed-config.md) | Typed Pydantic config, published JSON Schema | Accepted (revised) |
| [0015](0015-license-homogeneous-configs.md) | Dataset split into license-homogeneous configs; per-checkpoint model licences | Accepted (revised) |
| [0016](0016-import-linter.md) | Architecture enforced by import-linter | Accepted |
| [0017](0017-release-automation.md) | release-please (App token), PyPI Trusted Publishing, images built on the tag, cosign, SBOM, optional Action repo | Accepted (revised) |
| [0018](0018-single-ollama-server.md) | One Ollama server on the cluster for both A40s (`:11434` only; placement by Ollama, checked via `/api/ps`; generator/judge separation by the `llm-proxy` allow-list) | Accepted (amended by 0019) |
| [0019](0019-local-model-storage-small-disk.md) | Models on the cluster's own disk (`$CLUSTER_DATA_ROOT/Models`), one judge (`gemma3:12b`) for PR and nightly, no local datagen model (public text via GitHub Models, private data via the local judge model), data root a plain directory on the VM disk, cluster scripts copied over SSH | Accepted |
| [0020](0020-run-directory-lossless-store.md) | Run directory gains lossless `scored.jsonl`; atomic run writes; `tally_charges` for exact judge-request accounting | Accepted |

## Template (MADR-lite)

```markdown
# NNNN — <Title>

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD
- Tasks: <task IDs affected>

## Context
<forces, constraints, what breaks without a decision>

## Decision
<what we do, concretely>

## Alternatives considered
| Option | Why not |
| --- | --- |

## Consequences
- Positive: …
- Negative / cost: …
- Follow-ups: …
```
