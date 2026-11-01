# Docs targets (T0.4). `make docs` itself is the T0.1 target in the root Makefile (mkdocs build --strict).
.PHONY: docs-serve diagrams docs-mermaid

docs-serve:
	uv run mkdocs serve

# The module graph is rendered into the built site (never committed); run `make docs` first.
diagrams:
	scripts/gen_module_graph.sh site/architecture/generated

# Renders every fenced mermaid block under docs/ (pinned mermaid-cli, needs Node and a Chromium download).
docs-mermaid:
	scripts/check_mermaid.sh
