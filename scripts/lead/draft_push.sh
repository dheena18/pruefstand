#!/usr/bin/env bash
# usage: draft_push.sh [--dry-run] [--add <path>]... <worktree> <branch> <title> <commit-msg-file> <pr-body-file>
# ruff check + ruff format --check, commit, push (plain, only this branch, never forced), open a DRAFT PR against
# main. Staged: tracked changes plus the --add paths; other untracked files, files over 1 MB and secret-looking
# files are refused (exit 2). A message, body or title with a Claude-Session line or a "Generated with/by Claude
# Code" footer is refused (exit 2), and the committed message is re-checked before the push. Works from any cwd.
# --dry-run runs all the checks on a copy of the index and changes nothing.
set -u -o pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
parse_common "$@"
set -- "${REST[@]}"
[ "$#" -eq 5 ] || lead_die 2 "usage: draft_push.sh [--dry-run] [--add <path>]... <worktree> <branch> <title> <commit-msg-file> <pr-body-file>"
wt="$1"; branch="$2"; title="$3"
msgfile="$(abspath "$4")" || lead_die 2 "no such file: $4"
bodyfile="$(abspath "$5")" || lead_die 2 "no such file: $5"
forbid_footer "$msgfile"; forbid_footer "$bodyfile"
forbid_stdin "the PR title" <<<"$title"
require_gh
cd "$wt" || lead_die 1 "cannot cd to $wt"
require_branch "$branch"
check_ruff
if [ "$dry" = 1 ]; then
  idx="$(mktemp)"; cp "$(git rev-parse --git-path index)" "$idx" 2>/dev/null || true
  (export GIT_INDEX_FILE="$idx"; stage_changes) || { rm -f "$idx"; exit 2; }
  rm -f "$idx"
  echo "DRY-RUN: checks passed; would commit, push $branch and open a draft PR"; exit 0
fi
commit_all "$msgfile"
push_branch "$branch"
gh_ pr create --draft --repo dheena18/pruefstand --base main --head "$branch" --title "$title" --body-file "$bodyfile"
