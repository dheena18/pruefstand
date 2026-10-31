# Prüfstand — planning pack

Status: **planning, awaiting approval. No application code yet.**

Prüfstand is an open-source release gate for German-language RAG: it tests every prompt, model or
retrieval change on a pull request and blocks the merge only when quality really drops or data leaks
between tenants.

This folder becomes the root of the repository. Code is added task by task once the prompts are approved.

| Start here | What it is |
| --- | --- |
| [REVIEW.md](REVIEW.md) | Verdict on the original spec, gaps found, decisions taken, open questions |
| [CLAUDE.md](CLAUDE.md) | Ground rules every AI session follows (auto-loaded by Claude Code) |
| [docs/spec/SPEC.md](docs/spec/SPEC.md) | Spec v2 (authoritative) |
| [docs/architecture/](docs/architecture/README.md) | Diagrams + interface contracts |
| [docs/engineering/](docs/engineering/README.md) | Standards, testing, CI/CD, Docker, security, GPU cluster, AI workflow |
| [docs/adr/](docs/adr/README.md) | Architecture decision records |
| [tasks/TASKS.md](tasks/TASKS.md) | Phases → tasks → dependencies → estimates → tier (core / optional) + progress ticks |
| [tasks/PARALLEL-PLAN.md](tasks/PARALLEL-PLAN.md) | Wave schedule for up to 6 coding agents in parallel (worktrees, merge order, checkpoints) |
| [prompts/](prompts/README.md) | One ready-to-paste prompt per task + review and session playbooks |
| [docs/decisions.md](docs/decisions.md) | Decisions log (binding record, D1–D241); paste at session start |
| `docs/planning/reviews/` | History of the planning review rounds; `round10-resolution.md` (real cluster facts) is binding via D196–D210, `round11-resolution.md` (VM identity, `/v1/retrieve`, native Ollama, GitHub Pages) via D211–D241 |

Timeline: 20–26 weeks part-time with one session at a time; MVP (real gate blocks a bad PR on the A40s)
around week 12–14. With the parallel wave plan (`tasks/PARALLEL-PLAN.md`, ≤ 6 agents, owner review as the
bottleneck): **≈ 12–15 weeks**, M1 ≈ week 4, MVP ≈ week 8–10 (planning estimate, not a promise).
First weeks: create the TrueNAS VM and connect VS Code Remote-SSH (T0.7 S1–S2), T0.0 bootstrap on the VM, then
T0.7 (service user `pruefstand`, lock dir, data root on the VM disk, SSH key, tunnel unit) and the T0.6 cluster facts
check (go/no-go).

Machines: all development and execution happens on the TrueNAS VM `pruefstand-exec`; the A40 cluster
`cairo-s101lp` only serves models with Ollama (round 10, `docs/engineering/gpu-cluster.md`). On the VM the owner and
the coding agents work as the owner user; the gate executor runs as the system user `pruefstand` and both share
one GPU lock (`pruefstand-lock`, round 11). The dashboard is published on GitHub Pages.

Testing uses **real models and real CI only** (no fake LLM, no fake target): tier 1 runs the real
rag-demo with a small llama.cpp model and a GitHub Models judge on every PR; tier 2 runs the full
gate on the A40s (Ollama, reached from the VM). Free providers only.
