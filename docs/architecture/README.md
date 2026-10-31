# Architecture

How Prüfstand is built, from the system context down to individual functions. Every name in these
documents matches `interfaces.md` exactly; if they disagree, `interfaces.md` wins and the diagram
is a bug.

## Reading order

| # | Document | Answers |
| --- | --- | --- |
| 1 | [overview.md](overview.md) | Who uses the system, which containers exist, how they talk |
| 2 | [components.md](components.md) | Package layers, allowed imports, what each module owns |
| 3 | [interfaces.md](interfaces.md) | The exact contracts (models, signatures, file formats). **Authoritative.** |
| 4 | [call-graph.md](call-graph.md) | How functions call each other for every CLI command and the RAG query path |
| 5 | [sequences.md](sequences.md) | Time-ordered flows: tier-1 live gate, PR gate (owner dispatches the private executor), fork PR via `gate/pr-N`, baseline promotion, nightly + drift, dataset build, calibration, demo |
| 6 | [data-model.md](data-model.md) | Every persisted structure: run artefacts, DuckDB index, corpus, dataset, caches, Qdrant |
| 7 | [deployment.md](deployment.md) | Where things run: dev VM / laptop, hosted CI, private executor repo, executor VM `pruefstand-exec`, A40 cluster (Ollama only, models on its own disk), data root on the VM disk, dashboard-data repo, GitHub Pages dashboard, optional demo on the VM (Cloudflare Tunnel) |
| 8 | [../engineering/ci-cd.md](../engineering/ci-cd.md) | CI/CD pipelines (owned by the engineering docs); operations in [../ops/runbook.md](../ops/runbook.md) |
| – | `generated/` | Import graph rendered by `pydeps` in the docs build (T0.4); only a README is committed here, never edit by hand |

## Diagram conventions

- All diagrams are **Mermaid** so GitHub and the mkdocs site render them without plugins or images.
- Allowed types: `flowchart`, `sequenceDiagram`, `erDiagram`, `classDiagram`, `stateDiagram-v2`.
- Every diagram is followed by 2–4 lines explaining what to read from it.
- Labels with special characters (`ü`, `§`, `(`, `/`, `:`) are quoted: `A["Prüfstand (core)"]`.
- Never put `;` in a label or message text: it ends a statement in `sequenceDiagram` and
  `stateDiagram-v2` and truncates the line. Use `,` instead. `docs.yml` renders every block with a pinned
  `@mermaid-js/mermaid-cli` (T0.4), so a broken diagram fails CI.
- Node names use the code name (`evaluate_gate`, `Runner.run`), not a paraphrase.

| Shape / line | Meaning |
| --- | --- |
| `[rectangle]` | Process, module or function |
| `[(cylinder)]` | Persistent store (files, DB, index, cache) |
| `([stadium])` | External actor or third-party service |
| `{{hexagon}}` | Decision point |
| `-->` | Call / data flow (synchronous) |
| `-.->` | Async, optional or configuration-dependent flow |
| `==>` | Hard-fail / blocking path |
| `subgraph` with a `TRUST:` label | Network or trust boundary |

## Rules

1. **Diagrams are updated in the same PR as the code change** that makes them wrong. A PR that
   changes a public interface, a module dependency, a persisted field or a deployment component
   without updating the affected diagram fails review (`prompts/_review.md` check 14).
2. Diagrams describe the design, not aspirations. Optional/later parts (MCP server, extra adapters)
   are drawn with dashed lines and labelled "Phase 10".
3. The generated import graph in `generated/` must agree with [components.md](components.md);
   `make arch` (import-linter) enforces the same rules in CI.
