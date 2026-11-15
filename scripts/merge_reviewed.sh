#!/usr/bin/env bash
# usage: scripts/merge_reviewed.sh <pr> <sha> [reviewer-verdict]   (verdict may come from env REVIEW_VERDICT)
# Squash-merges PR <pr> only if its head is exactly <sha>, the 5 required checks are green on <sha>, and the PR
# touches no owner-merge path. Needs only what `gh` is already logged in with.
# Exit: 0 merged, 1 merge/API failed, 2 usage, 3 owner merge required, 4 checks not green, 5 head mismatch.
set -u -o pipefail
REPO="dheena18/pruefstand"
REQUIRED=(check scan images-gate docs-gate ui-check)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "$2" >&2; exit "$1"; }
gh_() { env -u GITHUB_TOKEN -u GH_TOKEN gh "$@"; }

{ [ "$#" -ge 2 ] && [ "$#" -le 3 ]; } || die 2 "usage: merge_reviewed.sh <pr> <sha> [reviewer-verdict]"
pr="$1"; sha="$2"; verdict="${3:-${REVIEW_VERDICT:-}}"
[[ "$pr" =~ ^[0-9]+$ ]] || die 2 "usage: <pr> must be a number"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die 2 "usage: <sha> must be a full 40-character lowercase commit sha"
[ -n "${verdict//[[:space:]]/}" ] || die 2 "usage: a non-empty reviewer verdict is required (third argument or REVIEW_VERDICT)"

head="$(gh_ pr view "$pr" --repo "$REPO" --json headRefOid --jq .headRefOid)" || die 1 "cannot read PR $pr"
[ "$head" = "$sha" ] || die 5 "head mismatch: PR head is not $sha"

files="$(gh_ api "repos/$REPO/pulls/$pr/files" --paginate --jq '.[]')" || die 1 "cannot read the file list of PR $pr"
printf '%s\n' "$files" | python3 -I "$here/merge_paths.py"
case "$?" in
  0) ;;
  3) die 3 "owner merge required" ;;
  *) die 1 "cannot evaluate the file list of PR $pr" ;;
esac

runs="$(gh_ api "repos/$REPO/commits/$sha/check-runs?filter=latest&per_page=100" --paginate \
  --jq '.check_runs[] | [.name, .status, (.conclusion // ""), (.app.slug // "")] | @tsv')" \
  || die 1 "cannot read the check runs of $sha"
for name in "${REQUIRED[@]}"; do
  rows="$(printf '%s\n' "$runs" | awk -F'\t' -v n="$name" '$1 == n')"
  [ -n "$rows" ] || die 4 "checks not green: $name missing on $sha"
  bad="$(printf '%s\n' "$rows" | awk -F'\t' '!($2 == "completed" && $3 == "success" && $4 == "github-actions")')"
  [ -z "$bad" ] || die 4 "checks not green: $name on $sha"
done

gh_ pr merge "$pr" --repo "$REPO" --squash --match-head-commit "$sha" || die 1 "merge failed"
gh_ pr comment "$pr" --repo "$REPO" --body "merged by lead: $sha; reviewer verdict: $verdict" \
  || echo "warning: merged, but the PR comment failed" >&2
echo "merged PR $pr at $sha"
