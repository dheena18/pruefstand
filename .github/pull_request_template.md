## Task ID

<!-- e.g. T1.6 -->

## Summary

<!-- What changed and why, in a few lines. -->

## Evidence (Done-when items)

<!-- One line per "Done when" item of the prompt: command + output, or link to the run.
     Tag [GPU] / [NET] / [DOCKER] / [HUMAN] items with the environment the evidence comes from. -->

## Interface changes

<!-- "none", or: what, why, impact; the doc + ADR are updated in this PR (CLAUDE.md section 1.5). -->

## Follow-ups

<!-- Work that belongs to other tasks, with task IDs (CLAUDE.md section 1.6). -->

## Checklist (CLAUDE.md section 10)

- [ ] All "Done when" items pass, evidence pasted above
- [ ] `make check` green locally and in CI
- [ ] Tests written first; coverage gates hold
- [ ] `docs/engineering/test-matrix.md` rows for my symbols are `covered`
- [ ] Docs updated: module README/docstrings, affected diagrams, `docs/decisions.md`
- [ ] No TODOs without a linked follow-up task ID
- [ ] Reviewed with `prompts/_review.md`; review findings resolved
