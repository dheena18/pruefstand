#!/usr/bin/env bash
# usage: resolve_merge.sh [--dry-run] <worktree> <branch> [pytest args...]
# Merges origin/main into <branch>. Append-only files (docs/decisions.md, docs/decisions/**, TASKS.md, ...) keep
# BOTH sides; any other conflict stops with NEEDS MANUAL. Refuses duplicate D-numbers and leftover conflict
# markers (never commits them). Then the optional pytest args run (bounded by LEAD_TEST_TIMEOUT seconds, default
# 1500, reported as TEST_TIMEOUT), then a plain push (never forced).
# Progress is written to <git-dir>/lead-resolve-merge.state and a killed run says where it stopped; rerunning the
# same command resumes (a half merge is detected through MERGE_HEAD). --dry-run only reports what a merge would
# conflict on. Works from any cwd.
set -u -o pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UNION=(python3 -I "$DIR/merge_union.py")
dry=0
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ "$#" -ge 2 ] || lead_die 2 "usage: resolve_merge.sh [--dry-run] <worktree> <branch> [pytest args...]"
wt="$1"; branch="$2"; shift 2
cd "$wt" || lead_die 1 "cannot cd to $wt"
require_branch "$branch"
state="$(git rev-parse --git-dir)/lead-resolve-merge.state"
phase=start

set_phase() { phase="$1"; [ "$dry" = 1 ] || printf 'phase=%s time=%s\n' "$1" "$(date -u +%FT%TZ)" >"$state"; }
on_exit() {
  local rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$phase" != done ]; then
    echo "STOPPED in phase '$phase' (exit $rc). Progress: $state. Fix the cause and rerun the same command; it resumes." >&2
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
if [ "$dry" = 0 ] && [ -f "$state" ] && ! grep -q 'phase=done' "$state"; then
  echo "previous run did not finish: $(cat "$state"); resuming"
fi

set_phase fetch
git fetch -q origin main || lead_die 1 "cannot fetch origin main"

if [ "$dry" = 1 ]; then
  phase=dry-run
  if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    echo "DRY-RUN: a merge is in progress; unmerged: $(git diff --name-only --diff-filter=U | tr '\n' ' ')"
  elif git merge-base --is-ancestor origin/main HEAD; then
    echo "DRY-RUN: origin/main is already merged; nothing to do"
  else
    out="$(git merge-tree --write-tree --name-only origin/main HEAD 2>&1)"; rc=$?
    if [ "$rc" -eq 0 ]; then echo "DRY-RUN: merges cleanly"
    else
      mapfile -t files < <(printf '%s\n' "$out" | sed -n '2,/^$/p' | grep -v '^$')
      echo "DRY-RUN: conflicts in: ${files[*]}"
      "${UNION[@]}" allowed "${files[@]}" && echo "DRY-RUN: all are append-only; both sides would be kept"
      exit $?
    fi
  fi
  exit 0
fi

set_phase merge
if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
  echo "merge in progress; resuming it"
elif git merge-base --is-ancestor origin/main HEAD; then
  echo "origin/main is already merged"
else
  [ -z "$(git status --porcelain --untracked-files=no)" ] || lead_die 2 "uncommitted changes in $PWD; commit or move them first"
  git merge --no-commit --no-ff origin/main >/dev/null 2>&1 || true
  if ! git rev-parse -q --verify MERGE_HEAD >/dev/null && ! git merge-base --is-ancestor origin/main HEAD; then
    lead_die 1 "git merge origin/main failed without a merge state (untracked files in the way?)"
  fi
fi

set_phase resolve
mapfile -t unmerged < <(git diff --name-only --diff-filter=U)
if [ "${#unmerged[@]}" -gt 0 ]; then
  "${UNION[@]}" resolve "${unmerged[@]}" || lead_die 1 "NEEDS MANUAL: resolve the files above by hand (git add them), then rerun"
  git add -- "${unmerged[@]}"
fi
[ -z "$(git diff --name-only --diff-filter=U)" ] || lead_die 1 "unmerged files remain; resolve them by hand and rerun"

set_phase verify
git add -u
if git diff --cached HEAD -U0 --no-color | grep -Eq '^\+(<<<<<<<|>>>>>>>)( |$)'; then
  echo MARKERS_LEFT
  git diff --cached HEAD -U0 --no-color | grep -E '^(\+\+\+ |\+(<<<<<<<|>>>>>>>)( |$))' | head -10
  exit 1
fi
decisions=(); [ -f docs/decisions.md ] && decisions+=(docs/decisions.md)
if [ -d docs/decisions ]; then while IFS= read -r f; do decisions+=("$f"); done < <(find docs/decisions -name '*.md' | sort); fi
if [ "${#decisions[@]}" -gt 0 ]; then "${UNION[@]}" dupes origin/main "${decisions[@]}" || exit 1; fi

set_phase commit
if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
  git commit -q --no-edit -m "merge main into $branch" || { echo COMMIT_FAIL; exit 1; }
fi

if [ "$#" -gt 0 ]; then
  set_phase test
  tout="$(mktemp)"
  timeout "${LEAD_TEST_TIMEOUT:-1500}" uv run pytest -q "$@" >"$tout" 2>&1; rc=$?
  tail -8 "$tout"; rm -f "$tout"
  [ "$rc" -ne 124 ] || { echo "TEST_TIMEOUT after ${LEAD_TEST_TIMEOUT:-1500}s; the merge is committed, rerun to continue"; exit 1; }
  [ "$rc" -eq 0 ] || { echo TEST_FAIL; exit 1; }
fi

set_phase push
out="$(mktemp)"
if ! git push -q origin "$branch" >"$out" 2>&1; then tail -3 "$out"; rm -f "$out"; echo PUSH_FAIL; exit 1; fi
rm -f "$out"
git log --oneline -1
set_phase done
