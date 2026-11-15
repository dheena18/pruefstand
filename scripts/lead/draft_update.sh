#!/usr/bin/env bash
# usage: draft_update.sh [--dry-run] <worktree> <branch> <commit-msg-file>
# ruff check + ruff format --check, commit (if anything is staged), push (never forced). Same message rule as
# draft_push.sh. Works from any cwd. --dry-run runs the checks and changes nothing.
set -u -o pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
dry=0
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ "$#" -eq 3 ] || lead_die 2 "usage: draft_update.sh [--dry-run] <worktree> <branch> <commit-msg-file>"
wt="$1"; branch="$2"
msgfile="$(abspath "$3")" || lead_die 2 "no such file: $3"
forbid_footer "$msgfile"
cd "$wt" || lead_die 1 "cannot cd to $wt"
require_branch "$branch"
check_ruff
if [ "$dry" = 1 ]; then echo "DRY-RUN: checks passed; would commit and push $branch"; exit 0; fi
commit_all "$msgfile"
push_branch "$branch"
git log --oneline -1
