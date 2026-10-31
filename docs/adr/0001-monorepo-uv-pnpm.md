# 0001 — Monorepo with uv workspace + pnpm, `src/` layout

- Status: Accepted
- Date: 2026-10-27
- Tasks: T0.1, T0.2, T8.1

## Context
There are three deliverables: the gate package, the reference RAG app and the dashboard. They share
schemas, CI and docs. Separate repos would mean three CI setups, and cross-cutting PRs (for example a
schema change that also updates the dashboard types) could not be reviewed as one change. AI sessions
also need one predictable layout.

## Decision
- One repo. Python 3.12 is managed by a **uv** workspace with members `packages/pruefstand` and `apps/rag-demo`.
- Each package uses the `src/` layout (`packages/pruefstand/src/pruefstand`, `apps/rag-demo/src/rag_demo`),
  so tests run against the installed package and not the working directory.
- The dashboard lives in `apps/dashboard` and is managed by **pnpm** (Node 22 LTS). It is not part of the uv workspace.
- Commit one `uv.lock` and one `pnpm-lock.yaml`. CI installs with `uv sync --locked` and `pnpm install --frozen-lockfile`.
- The root `Makefile` is the only entry point for checks (`make check`).

## Alternatives considered
| Option | Why not |
| --- | --- |
| Poetry | Slower, weaker workspace support, two tools for one job |
| Flat layout (`pruefstand/` at root) | Tests silently import the source tree, which hides packaging bugs |
| Polyrepo | Schemas drift across repos; three times the CI |
| Nx/Turborepo for everything | Too much tooling for one TypeScript app |

## Consequences
- Positive: one `make check`, schema and type changes land in one PR, locks are reproducible.
- Negative: contributors need both uv and pnpm; CI caches two ecosystems.
- Follow-up: rag-demo must not depend on pruefstand, even though they share a workspace (ADR-0016).
