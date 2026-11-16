# Decisions

**One file per decision: `docs/decisions/D<n>.md`** (D1211). The old single table was the most frequent
merge conflict (every PR appended a row at the same place), so a decision is now a file of its own and two
PRs adding two decisions never conflict. This page keeps what is not a numbered decision: the section
provenance, the task rows from before decision numbers, the pinned versions and the open questions.

- **Add a decision:** create `docs/decisions/D<n>.md` with the next free number inside your reserved range
  (see below). Never edit this page for a decision row, never append a `| D<n> |` row here (the guard
  `scripts/tests/test_decisions_unique.py` fails). Format: a front matter (`id`, `section`, optional
  `supersedes`, `adr`) and the decision text; copy any existing file, e.g. `docs/decisions/D1211.md`.
  Decisions are append-only: to change one, add a new file that says which it supersedes (`supersedes`)
  and link the ADR. The `id` must equal the file name; an id exists once.
- **Read all of them:** `uv run python scripts/build_decisions_index.py --stdout` prints the whole log
  sorted by number (paste it at the start of a session); `make docs` builds it as the page
  `decisions-log.md` (generated, git-ignored, never committed, so it cannot conflict).
- **Check:** `uv run python scripts/build_decisions_index.py --check` (also run by `make docs` and the
  test `scripts/tests/test_decisions_unique.py`).
- **A branch that still appends a row to the old table** (cut before D1211): merge `origin/main` into the PR
  branch (or rebase it non-interactively). The merge conflicts in `docs/decisions.md`; main's side brings the script, so
  run the one-step helper there, in the middle of the conflicted merge or rebase:

  ```text
  uv run python scripts/build_decisions_index.py --rebase-pending     # base ref: origin/main
  ```

  It finds the PR's side (`HEAD` normally and in a merge; the original tip, `rebase-merge/orig-head` or `rebase-apply/orig-head` under
  `git rev-parse --git-path`, during `git rebase`, where `HEAD` is main's side; it refuses with exit 2 if that cannot be told and for an **interactive** rebase, where the PR side would be
  the whole original tip: run it after the rebase from a merge of `origin/main`, or rebase non-interactively),
  moves the PR's rows into `docs/decisions/D<n>.md` and `git add`s them (idempotent; an id clash with
  different text or a duplicate id is refused), 3-way merges the PR's other edits of the old page (pinned
  versions, prose) onto main's page and stages it (exit 3 with conflict markers when that conflicts),
  and prints those edits. Conflict markers in the PR's copy: refused, exit 2, nothing written.
  Then `git rebase --continue` or `git commit`. By hand, the same in 5 steps:

  ```text
  PR=HEAD                                   # during git rebase: PR=$(cat $(git rev-parse --git-path rebase-merge/orig-head))  (or rebase-apply)
  git show $PR:docs/decisions.md > /tmp/mine.md                  # 1. the PR's copy of the old page
  git checkout origin/main -- docs/decisions.md                  # 2. main's new short page
  uv run python scripts/build_decisions_index.py --migrate-pending --decisions-md /tmp/mine.md   # 3.
  git add docs/decisions/                                        # 4. new files must be staged
  F='^(#|\| *D[0-9]+ *\|)'                                       # 5. re-apply other edits (pins, prose):
  diff -u <(git show $(git merge-base $PR origin/main):docs/decisions.md | grep -vE "$F") <(grep -vE "$F" /tmp/mine.md)
  ```

  The helper is for **stale PR branches only**. The layout branch itself (the one that holds the new page) resolves
  a conflict the other way round: keep its page (`git checkout --ours docs/decisions.md`) and run
  `--migrate-pending --decisions-md <copy of origin/main:docs/decisions.md>` (the tool rewrites that copy, so
  re-read main's page from git for any lossless check).

  Without a merge conflict, plain `uv run python scripts/build_decisions_index.py --migrate-pending`
  (it stages the new files) is enough. `--check` and the guard test also reject tight, indented or
  heading/prose forms of a decision entry on this page (`|D5|x|`, `### D5 ...`, `**D5** ...`, `1. D5 ...`, `> | D5 | ...`, `| x | D5 | y |`, `D5 is ...`):
  a prose line may not START with a D-number, reword it ("Decision D5 ...").

Reserved decision ranges (2026-11-03): disjoint ranges per agent avoid merge collisions, so gaps are intentional and rows are not renumbered: D520 T5.1, D540 T6.4, D560 wrapper PR, D580 checkpoint, D600 T3.1b prep, D620 T3.6, D900-D909 cassettes-models.yml.

## Sections of the former table

The `section` field of each decision file is the heading the row had under in the old log;
