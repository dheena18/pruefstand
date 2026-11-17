#!/usr/bin/env bash
# mirror_fork_pr.sh <N> [--reviewed] [--dry-run] (T6.2b S2; W2.5, D104, X2.3, R13 P1.2): the owner's step for a
# FORK PR. After reading the diff, the owner runs it with --reviewed: it pushes the fork PR's current head
# (fetched as refs/pull/<N>/head) to the branch gate/pr-<N> of this repo and nothing else. It never opens a
# PR (a same-repo PR would run fork code with repo permissions) and never labels anything; it prints the
# owner's next step, the dispatch of the private gate-executor.yml, which the VM token cannot run.
# Refused (exit 1) when the diff against main touches .github/**, infra/runner/**, infra/gate-executor/**,
# action/** or this script, on either side of a rename (--no-renames, review #214). --dry-run prints what
# would be pushed instead of pushing.
# Env: REMOTE (default origin), MAIN_REF (default <REMOTE>/main).
# Exit: 0 pushed (or dry run), 1 refused / not reviewed / git failure, 64 usage.
set -euo pipefail

die() { echo "mirror_fork_pr: $1" >&2; exit "${2:-1}"; }
usage="usage: mirror_fork_pr.sh <PR number> [--reviewed] [--dry-run]"
[ "$#" -ge 1 ] && [ "$#" -le 3 ] || die "$usage" 64
pr="$1"
shift
[[ "$pr" =~ ^[1-9][0-9]{0,6}$ ]] || die "$usage" 64
reviewed=0
dry_run=0
for arg in "$@"; do
  case "$arg" in
    --reviewed) reviewed=1 ;;
    --dry-run) dry_run=1 ;;
    *) die "$usage" 64 ;;
  esac
done
remote="${REMOTE:-origin}"
main_ref="${MAIN_REF:-$remote/main}"

git fetch -q "$remote" main "+refs/pull/$pr/head:refs/mirror-fork/pr-$pr"
head="$(git rev-parse "refs/mirror-fork/pr-$pr^{commit}")"
denied="$(git diff --name-only --no-renames "$main_ref...$head" | grep -E '^(\.github/|infra/runner/|infra/gate-executor/|action/|scripts/mirror_fork_pr\.sh$)' || true)"
if [ -n "$denied" ]; then
  printf 'mirror_fork_pr: refused: the diff touches protected paths:\n%s\n' "$denied" >&2
  exit 1
fi
[ "$reviewed" -eq 1 ] || die "not pushed: review the diff of PR $pr ($head) first, then rerun with --reviewed" 1

target="refs/heads/gate/pr-$pr"
if [ "$dry_run" -eq 1 ]; then
  echo "dry run: git push $remote +$head:$target"
else
  # gate/pr-<N> follows the fork head the owner reviewed; the executor gates it only while it equals the
  # fork PR's head at dispatch time (X2.3), so moving it is the intended effect.
  git push -q "$remote" "+$head:$target"
  echo "pushed $head to gate/pr-$pr"
fi
echo "next (owner, browser or GitHub mobile app): gh workflow run gate-executor.yml -R dheena18/pruefstand-gate -f pr=$pr"
