# Generated module graph

The import graph of the `pruefstand` package is rendered by `pydeps` (`scripts/gen_module_graph.sh`,
T0.4) into the built site, never committed. Do not add generated files to this directory.

- Published at <https://dheena18.github.io/pruefstand/docs/architecture/generated/module-deps.svg>
  (written by `docs.yml` on every Pages deploy).
- Locally: `make docs && make diagrams` writes `site/architecture/generated/module-deps.svg`.

The layer rules the graph must obey are in [components.md](../components.md) and are enforced by
`make arch` (import-linter, ADR-0016); the graph is for reading, the contract is the check.
