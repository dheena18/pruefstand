#!/usr/bin/env bash
# usage: draft_push.sh [--dry-run] <worktree> <branch> <title> <commit-msg-file> <pr-body-file>
# ruff check + ruff format --check, commit with the message file, push (never forced), open a DRAFT PR against
# main. CI runs the full checks. Refuses (exit 2) a message or body with a Claude-Session line or a
# "Generated with Claude Code" footer. Works from any cwd. --dry-run runs the checks and changes nothing.
set -u -o pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
dry=0
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ "$#" -eq 5 ] || lead_die 2 "usage: draft_push.sh [--dry-run] <worktree> <branch> <title> <commit-msg-file> <pr-body-file>"
wt="$1"; branch="$2"; title="$3"
msgfile="$(abspath "$4")" || lead_die 2 "no such file: $4"
bodyfile="$(abspath "$5")" || lead_die 2 "no such file: $5"
forbid_footer "$msgfile"; forbid_footer "$bodyfile"
cd "$wt" || lead_die 1 "cannot cd to $wt"
require_branch "$branch"
check_ruff
if [ "$dry" = 1 ]; then echo "DRY-RUN: checks passed; would commit, push $branch and open a draft PR"; exit 0; fi
commit_all "$msgfile"
push_branch "$branch"
gh_ pr create --draft --repo dheena18/pruefstand --base main --head "$branch" --title "$title" --body-file "$bodyfile"
