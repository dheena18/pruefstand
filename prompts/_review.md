# Review prompt (run on every PR before merge)

Use in a **fresh** Claude Code session (or a subagent) on the PR branch, so the reviewer does not
share the implementer's assumptions. Run the second-family review with GitHub Models
(`gh models run <model> < review-input.md`); Copilot code review is optional (not part of GitHub Pro).

```text
You are reviewing PR <number> for Prüfstand, task <ID>. You did not write this code.
Read CLAUDE.md, docs/decisions.md, prompts/<ID>-*.md, docs/architecture/interfaces.md and the diff
(`git diff origin/main...HEAD`). Then check, and for each item answer PASS or FAIL with file:line:

Scope
 1. Does the diff do exactly task <ID>, nothing from other tasks?
 2. Is every "Done when" item met, with evidence I can re-run?
Contracts
 3. Do all public names/fields/signatures match interfaces.md? Any change flagged + ADR updated?
 4. Do persisted models carry schema_version? Are JSON Schemas regenerated (`make schemas`)?
Correctness
 5. Edge cases: empty input, one case, all-NaN, unicode (ä ö ü ß, combining marks), very long text,
    timeouts, retries, partial failures. Which are untested?
 6. Statistics/metrics: is the math right? Recompute one worked example by hand.
 7. Determinism: every random op seeded; no wall-clock or ordering dependence in results.
Security
 8. Secrets never logged/persisted; no shell=True; no eval; no unsafe YAML load; timeouts on I/O.
 9. Tenant isolation: could any path return or log another tenant's data?
10. CI changes: no `pull_request_target` with checkout of PR code; minimal `permissions:`; actions pinned by SHA.
Quality
11. Layering respected (`make arch`); no direct litellm/openai import outside llm/.
12. Files ≤ 300 lines, functions ≤ 50 lines, no dead code, no commented-out code, no TODO without task ID.
13. Tests: written first? meaningful assertions (not just "no exception")? property tests where listed?
14. Docs: docstrings, decisions.md, affected diagrams updated?

Output: a table of the 14 checks, then a list of findings ordered by severity
(blocker / major / minor) with a concrete fix for each. Do not rewrite the code yourself.
```
