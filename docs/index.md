# Prüfstand

Prüfstand is an open-source release gate for German-language RAG: it tests every prompt, model or
retrieval change on a pull request and blocks the merge only when quality really drops or data leaks
between tenants. Tests use real models and a real stack (no fake LLM, no fake target); free providers only.

| Start here | What it is |
| --- | --- |
| [Review](_external/review.md) | Verdict on the original spec and the planning review rounds |
| [Spec](spec/SPEC.md) | Spec v2 (authoritative) |
| [Decisions](decisions.md) | Binding decisions log |
| [ADRs](adr/README.md) | Architecture decision records |
| [Architecture](architecture/README.md) | Diagrams and interface contracts |
| [Engineering](engineering/README.md) | Standards, testing, CI/CD, Docker, security, GPU cluster, AI workflow |
| [Tasks](_external/tasks.md), [Prompts](_external/prompts.md) | Task list and one prompt per task |

The source lives in the repository at <https://github.com/dheena18/pruefstand>; the dashboard is served at the
site root, these docs under `/docs/`.
