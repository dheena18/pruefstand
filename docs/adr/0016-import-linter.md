# 0016 — Architecture enforced with import-linter

- Status: Accepted (revised round 11, D232: typecheck/test roots for `infra/**` helpers)
- Date: 2026-10-27
- Tasks: T0.1, T0.2, and every task after them

## Context
Many independent AI sessions write this codebase. Without enforcement, the layering erodes (gate starts
importing llm, rag-demo starts importing the test set) and the diagrams stop matching the code.

## Decision
`.importlinter` contracts, run by `make arch` in CI as a required check:

| Contract | Type | Rule |
| --- | --- | --- |
| layers | layers | `cli > pipeline > (report \| gate \| runner \| dataset) > metrics > (judges \| adapters \| store \| ingest \| perturb \| attacks) > llm > core` |
| gate-pure | forbidden | `pruefstand.gate` must not import `llm, adapters, store, runner, judges, metrics, httpx, litellm` |
| llm-gateway | forbidden | only `pruefstand.llm.backends.litellm` may import `litellm`, `openai`, `anthropic` |
| deterministic-no-llm | forbidden | `pruefstand.metrics.deterministic` must not import `pruefstand.llm`, `pruefstand.judges` |
| sut-independent | forbidden | `rag_demo` must not import `pruefstand` |
| core-leaf | forbidden | `pruefstand.core` imports no other `pruefstand.*` module |
| siblings-independent | independence | modules in the same row never import each other; shared types live in `core` (interfaces.md "Where types live") |

The MCP server `pruefstand.mcp` (T10.1) sits at the `cli` layer.
Only `pipeline` combines `ingest` and `attacks` (for example when it plants injection docs into the corpus).

Type checking and tests also cover the Python helpers outside `packages/` and `apps/` (Y6.4, D232):
mypy/pytest paths include `infra/vm/**` and `infra/cluster/**`, and `infra/gate-executor/orchestrator`
and `infra/gate-executor/llm-proxy` are appended to the one root list (D177; `pythonpath` = `mypy_path`),
because their directory names are not valid package names. The proxy module is `llm_proxy.py` (no
top-level clash with `infra/gpu/rerank/app.py`). These helpers are outside the `.importlinter` contracts.

`scripts/check_code_limits.py` (T0.1 S8, run by `make file-size`) also fails on any `datasets/` string in
`apps/**/*.py`, because import-linter cannot see file paths. CI renders a `pydeps` graph to
`docs/architecture/generated/` as well.

## Alternatives considered
| Option | Why not |
| --- | --- |
| Code review only | Does not keep up with the volume of AI-written PRs |
| One package per layer | Too much packaging overhead |

## Consequences
- Positive: an architecture violation fails CI with a precise message.
- Negative: a legitimate new import edge needs an ADR that updates the contract.
- Because every shared model and protocol lives in `core`, same-row modules can depend on one another's
  types without importing each other.
- Accepted dependency: **polars** for analysis code only (`judges.calibration`, `store.RunIndex`, `experiments/`).
  `core` models use plain tuples, and `gate` uses NumPy.
