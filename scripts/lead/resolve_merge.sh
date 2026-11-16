#!/usr/bin/env bash
# usage: resolve_merge.sh [--dry-run] <worktree> <branch> [pytest args...]
# Merges origin/main into <branch>. Append-only files (docs/decisions.md, TASKS.md, ...) keep BOTH sides; any other
# conflict (docs/decisions/** included) stops with NEEDS MANUAL. Refuses duplicate D-numbers and conflict markers a
# merge would add (never committed). A merge already in progress must be a merge of origin/main (or an ancestor).
# Optional pytest args then run in their own process group, bounded by LEAD_TEST_TIMEOUT seconds (default 1500,
# reported as TEST_TIMEOUT); Ctrl-C/TERM of this script kills that group. Then a plain push of exactly this
# branch (never forced).
# Progress is written to <git-dir>/lead-resolve-merge.state; a killed run says where it stopped and a rerun resumes
# (half merges are detected through MERGE_HEAD, conflict files are rebuilt from the index). One run per worktree:
# the lock (flock, inherited by pytest) refuses a second run while the first, or its pytest, still lives.
# --dry-run reports what a merge would conflict on, using the LOCAL origin/main (no fetch, no changes).
set -u -o pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UNION=("$PY_BIN" -I "$DIR/merge_union.py")
dry=0
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ "$#" -ge 2 ] || lead_die 2 "usage: resolve_merge.sh [--dry-run] <worktree> <branch> [pytest args...]"
wt="$1"; branch="$2"; shift 2
cd "$wt" || lead_die 1 "cannot cd to $wt"
require_branch "$branch"
gitdir="$(git rev-parse --git-dir)"
state="$gitdir/lead-resolve-merge.state"
phase=start
child_pgid=""

set_phase() { phase="$1"; [ "$dry" = 1 ] || printf 'phase=%s time=%s\n' "$1" "$(date -u +%FT%TZ)" >"$state"; }
kill_child() {
  [ -n "$child_pgid" ] || return 0
  kill -TERM -- "-$child_pgid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 -- "-$child_pgid" 2>/dev/null || break; sleep 0.5; done
  kill -KILL -- "-$child_pgid" 2>/dev/null || true
  child_pgid=""
}
on_exit() {
  local rc=$?
  trap - EXIT
  kill_child
  if [ "$rc" -ne 0 ] && [ "$phase" != done ]; then
    echo "STOPPED in phase '$phase' (exit $rc). Progress: $state. Fix the cause and rerun the same command; it resumes." >&2
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

if [ "$dry" = 0 ]; then
  exec 9>"$gitdir/lead-resolve-merge.lock"
  flock -n 9 || lead_die 1 "a previous resolve_merge run (or its pytest; see child_pgid in $state) is still running in this worktree; wait for it (LEAD_TEST_TIMEOUT bounds it) or stop that process group, then rerun"
  if [ -f "$state" ] && ! grep -q 'phase=done' "$state"; then echo "previous run did not finish: $(tr '\n' ' ' <"$state"); resuming"; fi
  set_phase fetch
  git fetch -q origin main || lead_die 1 "cannot fetch origin main"
else
  phase=dry-run
  git rev-parse -q --verify origin/main >/dev/null || lead_die 1 "no local origin/main; fetch first"
  echo "DRY-RUN: using the local origin/main (no fetch)"
fi

if [ "$dry" = 1 ]; then
  if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    mapfile -t files < <(git diff --name-only --diff-filter=U)
    echo "DRY-RUN: a merge is in progress; unmerged: ${files[*]:-none}"
    if [ "${#files[@]}" -gt 0 ]; then
      "${UNION[@]}" allowed "${files[@]}" && echo "DRY-RUN: all are append-only; both sides would be kept"
      exit $?
    fi
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
  mh="$(git rev-parse MERGE_HEAD)"
  git merge-base --is-ancestor "$mh" origin/main \
    || lead_die 1 "a merge of something else is in progress (MERGE_HEAD $mh is not origin/main or an ancestor of it); finish it or run 'git merge --abort' first"
  echo "merge of origin/main in progress; resuming it"
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
# Once origin/main has the per-decision layout (docs/decisions/D<n>.md, PR #160), the old table page is no longer
# append-only: a conflict on it, or a `| D<n> |` row this branch adds to it, needs the migration helper.
per_file=0
[ -n "$(git ls-tree --name-only origin/main docs/decisions/ | head -n 1)" ] && per_file=1
recipe="NEEDS MANUAL: origin/main keeps decisions as docs/decisions/D<n>.md files. Move this branch's rows with 'uv run python scripts/build_decisions_index.py --rebase-pending' (recipe in docs/decisions.md on main), git add the result, then rerun"
mapfile -t unmerged < <(git diff --name-only --diff-filter=U)
for f in "${unmerged[@]}"; do
  [ "$per_file" = 1 ] && [ "$f" = docs/decisions.md ] && lead_die 1 "$recipe"
  stages="$(git ls-files -u -- "$f" | awk '{print $3}' | LC_ALL=C sort -u | tr '\n' ' ')"
  case "$stages" in
    *2*3*) ;;  # a content merge has our side (2) and theirs (3); the base (1) is absent for add/add
    *) lead_die 1 "NEEDS MANUAL: $f has no ours/theirs pair in the index (deleted on one side?); resolve it by hand, git add it, then rerun" ;;
  esac
  if grep -q '^<<<<<<< ' "$f" 2>/dev/null; then
    "${UNION[@]}" resolve "$f" || lead_die 1 "NEEDS MANUAL: resolve the files above by hand (git add them), then rerun"
  else  # a finished resolution by an earlier run: accepted only if it still holds every line of both sides
    { [ -e "$f" ] && "${UNION[@]}" allowed "$f" && "${UNION[@]}" covered "$f"; } \
      || lead_die 1 "NEEDS MANUAL: $f is unmerged without conflict markers and does not contain both sides; resolve it, git add it, then rerun"
  fi
  git add -- "$f"
done
[ -z "$(git diff --name-only --diff-filter=U)" ] || lead_die 1 "unmerged files remain; resolve them by hand and rerun"

set_phase verify
# The commit takes the index only. Unstaged edits to a file the merge touched would be checked but not committed.
# LC_ALL=C: sort and comm must use the same byte order, or comm misses names (en_US.UTF-8 ignores punctuation).
mapfile -t overlap < <(LC_ALL=C comm -12 <(git diff --cached --name-only HEAD | LC_ALL=C sort) <(git diff --name-only | LC_ALL=C sort))
if [ "${#overlap[@]}" -gt 0 ]; then
  lead_die 1 "unstaged edits to files of this merge (git add them, or git checkout them, then rerun): ${overlap[*]}"
fi
if git diff --cached HEAD -U0 --no-color | grep -Eq '^\+(<<<<<<<|>>>>>>>)( |$)'; then
  echo MARKERS_LEFT
  git diff --cached HEAD -U0 --no-color | grep -E '^(\+\+\+ |\+(<<<<<<<|>>>>>>>)( |$))' | head -10
  exit 1
fi
if [ "$per_file" = 1 ] && [ -f docs/decisions.md ] \
  && git diff --cached origin/main -- docs/decisions.md | grep -Eq '^\+[[:space:]]*\|[[:space:]]*D[0-9]+[[:space:]]*\|'; then
  lead_die 1 "$recipe"
fi
[ ! -f docs/decisions.md ] || "${UNION[@]}" dupes origin/main docs/decisions.md || exit 1

set_phase commit
if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
  git commit -q --no-edit -m "merge main into $branch" || { echo COMMIT_FAIL; exit 1; }
fi

if [ "$#" -gt 0 ]; then
  set_phase test
  tout="$(mktemp)"
  setsid timeout -k 30 "${LEAD_TEST_TIMEOUT:-1500}" "$UV_BIN" run pytest -q "$@" >"$tout" 2>&1 &
  child_pgid=$!
  printf 'child_pgid=%s\n' "$child_pgid" >>"$state"
  wait "$child_pgid"; rc=$?
  child_pgid=""
  tail -8 "$tout"; rm -f "$tout"
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then echo "TEST_TIMEOUT after ${LEAD_TEST_TIMEOUT:-1500}s; the merge is committed, rerun to continue"; exit 1; fi
  [ "$rc" -eq 0 ] || { echo TEST_FAIL; exit 1; }
fi

set_phase push
check_branch_messages
out="$(mktemp)"
if ! git push -q origin "refs/heads/$branch:refs/heads/$branch" >"$out" 2>&1; then tail -3 "$out"; rm -f "$out"; echo PUSH_FAIL; exit 1; fi
rm -f "$out"
git log --oneline -1
set_phase done
