# <ID> — <Title>

| Field | Value |
| --- | --- |
| Phase | <N — name> |
| Depends on | <task IDs, must be merged> |
| Unblocks | <task IDs> (informational; the authoritative dependency graph is the "Depends" column of `tasks/TASKS.md`) |
| Who | AI / AI+H |
| Suggested model | Opus / Sonnet |
| Branch | `feat/<ID>-<slug>` |
| Estimate | <h> |

## Read first (in this order)

1. `CLAUDE.md` (auto-loaded) — ground rules
2. `docs/decisions.md`
3. `docs/spec/SPEC.md` §<sections>
4. `docs/architecture/interfaces.md` §<sections>
5. `docs/adr/<relevant ADRs>`
6. <existing code paths this task builds on>

## Goal

<One or two sentences: what exists after this task that did not exist before.>

## Context

<Only what the implementer needs that is not in the docs above; ≤ 10 lines.>

## Subtasks

- [ ] S1 <smallest verifiable step>
- [ ] S2 …

## Files to create / change

```text
<path>            <purpose>
```

## Interfaces (must match `interfaces.md` exactly)

```python
<signatures this task implements or consumes>
```

## Tests to write first

| Test file | Cases |
| --- | --- |
| `tests/unit/...` | <concrete inputs → expected outputs> |

## Constraints and non-goals

- <what not to do, what belongs to another task>

## Done when (show evidence for each)

- [ ] `make check` green
- [ ] <specific command> → <specific expected output>

## Docs to update

- [ ] `docs/decisions.md` (one line per decision)
- [ ] <diagram / README / module docstring>

## Prompt to paste

```text
You are a senior engineer on Prüfstand. Task <ID>: <title>.
Read, in order: CLAUDE.md, docs/decisions.md, prompts/<this file>, and the sections it lists.
1. Post a plan: files, interfaces, tests. Wait for my "go" only if an interface in
   docs/architecture/interfaces.md must change; otherwise continue.
2. Write the failing tests from "Tests to write first", run them, show they fail.
3. Implement until they pass. Keep files ≤ 300 lines, functions ≤ 50 lines.
4. Run `make check`. Fix everything; do not weaken any rule.
5. Self-review with prompts/_review.md and fix findings.
6. Update the docs listed under "Docs to update".
7. Reply with: summary, evidence for every "Done when" item, interface changes (or "none"),
   follow-ups with task IDs.
```
