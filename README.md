# Prüfstand

Prüfstand is an open-source release gate for German-language RAG: it tests every prompt, model or
retrieval change on a pull request and blocks the merge only when quality really drops or data leaks
between tenants. Tests use real models and a real stack (no fake LLM, no fake target); free providers only.

Status: **in progress** (Phase 0, repository scaffold). The documentation lives in [`docs/`](docs/).

| Start here | What it is |
| --- | --- |
| [CLAUDE.md](CLAUDE.md) | Ground rules for every session: tooling, layers, code and test rules |
| [docs/spec/SPEC.md](docs/spec/SPEC.md) | Spec v2 (authoritative) |
| [docs/architecture/](docs/architecture/README.md) | Diagrams and interface contracts |
| [docs/engineering/](docs/engineering/README.md) | Standards, testing, CI/CD, Docker, security, GPU cluster, AI workflow |
| [docs/adr/](docs/adr/README.md) | Architecture decision records |
| [docs/decisions.md](docs/decisions.md) | Binding decisions log |
| [tasks/TASKS.md](tasks/TASKS.md), [prompts/](prompts/README.md) | Tasks and one prompt per task |
| [REVIEW.md](REVIEW.md) | Verdict on the original spec and the planning review rounds |

## Development

```bash
make install   # uv sync --all-packages --all-extras
make check     # lint, typecheck, arch, file-size, coverage (what CI runs)
uv run pruefstand --help
```

Python 3.12 and `uv` only; see `CLAUDE.md` §3 for every Make target.
