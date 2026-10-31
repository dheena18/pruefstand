# Engineering handbook

These docs define how Prüfstand is built. `CLAUDE.md` is the short, binding version of them. When
the two disagree, `CLAUDE.md` wins, and the disagreement is a bug to fix here.

| Doc | Covers |
| --- | --- |
| [coding-standards.md](coding-standards.md) | Python + TypeScript style, ruff/mypy config, naming, docstrings, errors, logging, size limits, module README |
| [testing-strategy.md](testing-strategy.md) | Test pyramid, every test layer, all harnesses (real live stack on CPU, real bug switches, cassettes of real responses, Testcontainers, statistical validation, GPU smoke, UI); no fakes (ADR-0008), coverage, flaky-test policy |
| [ci-cd.md](ci-cd.md) | Every GitHub workflow, pipeline diagrams, required checks, caching, self-hosted runner security, CD stages |
| [docker.md](docker.md) | Images, Dockerfile template, compose profiles, GPU reservation, tagging/signing, scanning |
| [git-workflow.md](git-workflow.md) | Branches, Conventional Commits, PR template, CODEOWNERS, review flow, merge policy |
| [security.md](security.md) | Threat model (STRIDE-lite), controls, and the tests that prove them |
| [gpu-cluster.md](gpu-cluster.md) | 2×A40 allocation, Ollama servers and modes (day/night/datagen), quantisation, memory budget, VM identities, tunnels and `llm-proxy` networking (D242) |
| [ai-workflow.md](ai-workflow.md) | How Claude Code, GitHub Models (second-family review), optional Copilot and local models are used; WSL2 setup; sessions, review loops, worktrees, hooks |
| [release.md](release.md) | Versioning, release steps, artefacts and where they go |

Related: [`../architecture/interfaces.md`](../architecture/interfaces.md) ·
[`../decisions.md`](../decisions.md) · [`../adr/`](../adr/README.md) · [`../../tasks/TASKS.md`](../../tasks/TASKS.md)
