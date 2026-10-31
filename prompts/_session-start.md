# How to run one task (session playbook)

1. `git switch main && git pull && git switch -c feat/<ID>-<slug>`
2. Open Claude Code in the repo root (CLAUDE.md loads automatically).
3. Paste the **Prompt to paste** block from `prompts/<ID>-*.md`.
4. Let it post the plan. Approve only if it lists tests before implementation and touches only
   the files in the prompt. If it proposes an interface change, read its paragraph and decide.
5. When it reports done, re-run the "Done when" commands yourself.
6. Open the PR (template fills in). CI runs. Run the second-family review: `gh models run <model> < review-input.md` (Copilot code review is optional).
7. Open a **new** session and paste `prompts/_review.md`. Fix blockers/majors in the first session
   (or a new one with the review output).
8. Merge (squash, Conventional Commit title). Tick the task in `tasks/TASKS.md`.
9. If the session goes in circles: stop, start fresh with CLAUDE.md + decisions.md + the prompt +
   a 5-line summary of what is already done.

## Model choice

| Situation | Use |
| --- | --- |
| Statistics, security, CI hardening, architecture-touching tasks | Claude Opus |
| Standard implementation from a precise prompt | Claude Sonnet |
| Second-opinion PR review | GitHub Models via `gh models run` (other model family); Copilot code review optional (not in GitHub Pro) |
| Bulk text work (German question rewrites, labeling suggestions) | Local datagen model (`llama` 70B-class `Q4_K_M`, weekend datagen mode) on the A40s via Ollama, called from the VM |

## Parallel sessions

Tasks in the same "parallel lane" (`tasks/TASKS.md`, Critical path) can run at the same time in
separate git worktrees. Never run two sessions that edit the same files.
