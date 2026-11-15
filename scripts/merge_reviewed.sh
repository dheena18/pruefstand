#!/usr/bin/env bash
# usage: scripts/merge_reviewed.sh <pr> <sha> <reviewer-verdict>   (verdict: third argument, or env REVIEW_VERDICT)
# Squash-merges PR <pr> (open, not draft, base main) only if
#   - this script and scripts/merge_paths.py have the same CONTENT as on main of the origin
#     (fetched into the private ref refs/merge-reviewed/main; origin must be the public repo), else exit 3,
#   - the PR head is exactly <sha> (exit 5),
#   - the changes from the merge base to <sha> touch no owner-merge path (exit 3 "owner merge required"),
#   - every context the live ruleset requires is verified on <sha> (exit 4): the ruleset must list at least
#     one; check, scan, images-gate, docs-gate, ui-check = the job of that name in the NEWEST pull_request run
#     of ci.yml / security.yml / build-images.yml / docs.yml / ui.yml on <sha> that belongs to this PR (base main)
#     succeeded; pruefstand/gate = a success status set by pruefstand-bot[bot], verified ONLY IF the ruleset
#     lists it (it does not today, so gated PRs can merge without tier 2); any other context is unverifiable.
# Needs only what `gh` is already logged in with. Exit: 0 merged, 1 failure, 2 usage, 3 owner merge
# required, 4 checks not green, 5 head mismatch or PR not mergeable here.
set -u -o pipefail
REPO="dheena18/pruefstand"

# Resolve every tool once, before PATH is narrowed; refuse a gh that lives under $HOME.
GH="$(command -v gh 2>/dev/null || true)"
[ -n "$GH" ] || { echo "gh not found" >&2; exit 1; }
GH="$(readlink -f "$GH")"
case "$GH" in "${HOME:-/nonexistent-home}"/*) echo "refusing a gh under HOME" >&2; exit 1 ;; esac
export PATH=/usr/local/bin:/usr/bin:/bin
ENV=/usr/bin/env; GIT=/usr/bin/git; PY=/usr/bin/python3; AWK=/usr/bin/awk; TR=/usr/bin/tr; CMP=/usr/bin/cmp
EXPECTED_ORIGIN="https://github.com/$REPO.git"
MAIN_REF="refs/merge-reviewed/main"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

die() { echo "$2" >&2; exit "$1"; }
gh_() { "$ENV" -u GITHUB_TOKEN -u GH_TOKEN "$GH" "$@"; }
tsv_field() { printf '%s\n' "$1" | "$AWK" -F'\t' -v i="$2" 'NR == 1 { print $i }'; }

{ [ "$#" -ge 2 ] && [ "$#" -le 3 ]; } || die 2 "usage: merge_reviewed.sh <pr> <sha> <reviewer-verdict>"
pr="$1"; sha="$2"; verdict="${3:-${REVIEW_VERDICT:-}}"
[[ "$pr" =~ ^[0-9]+$ ]] || die 2 "usage: <pr> must be a number"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die 2 "usage: <sha> must be a full 40-character lowercase commit sha"
verdict="${verdict%%$'\n'*}"; verdict="$(printf '%s' "$verdict" | LC_ALL=C "$TR" -d '\000-\037\177')"
verdict="${verdict//@/(at)}"; verdict="${verdict:0:300}"
[ -n "${verdict//[[:space:]]/}" ] || die 2 "usage: a non-empty reviewer verdict is required (third argument)"

# 1. The code that runs here must be the code on main of the real origin. No hash-object (clean filters,
#    .git/info/attributes): compare raw blob content; main is fetched into a private ref, not origin/main.
repo="$("$GIT" -C "$here" rev-parse --show-toplevel)" || die 1 "not inside a git checkout"
[ "$here" = "$repo/scripts" ] || die 3 "script differs from origin/main: unexpected location"
origin_url="$("$GIT" -C "$repo" config --get remote.origin.url)" || die 1 "no origin remote"
{ [ "$origin_url" = "$EXPECTED_ORIGIN" ] || [ "$origin_url" = "https://github.com/$REPO" ]; } \
  || die 3 "origin is not $EXPECTED_ORIGIN"
"$GIT" -C "$repo" fetch -q origin "+refs/heads/main:$MAIN_REF" || die 1 "cannot fetch main of origin"
for f in merge_reviewed.sh merge_paths.py; do
  "$GIT" -C "$repo" cat-file blob "$MAIN_REF:scripts/$f" 2>/dev/null | "$CMP" -s - "$here/$f" \
    || die 3 "script differs from origin/main: owner merge required"
done

# 2. The PR: open, not draft, base main, head == sha.
pr_state() { gh_ pr view "$pr" --repo "$REPO" --json baseRefName,state,isDraft,headRefOid \
  --jq '[.baseRefName, .state, (.isDraft | tostring), .headRefOid] | @tsv'; }
info="$(pr_state)" || die 1 "cannot read PR $pr"
[ "$(tsv_field "$info" 4)" = "$sha" ] || die 5 "head mismatch: PR head is not $sha"
[ "$(tsv_field "$info" 1)" = "main" ] || die 5 "PR base is not main"
[ "$(tsv_field "$info" 2)" = "OPEN" ] || die 5 "PR is not open"
[ "$(tsv_field "$info" 3)" = "false" ] || die 5 "PR is a draft"

# 3. Owner-merge paths, from the commits themselves (no renames: both sides of a rename are listed).
"$GIT" -C "$repo" fetch -q origin "+refs/heads/main:$MAIN_REF" "$sha" || die 1 "cannot fetch $sha"
base="$("$GIT" -C "$repo" merge-base "$MAIN_REF" "$sha")" || die 1 "no merge base with main"
names="$(mktemp)"; trap 'rm -f "$names"' EXIT
"$GIT" -C "$repo" diff --name-only --no-renames -z "$base" "$sha" >"$names" || die 1 "cannot diff $sha"
"$PY" -I "$here/merge_paths.py" <"$names"
case "$?" in
  0) ;;
  3) die 3 "owner merge required" ;;
  *) die 1 "cannot evaluate the file list of PR $pr" ;;
esac

# 4. Required checks: exactly the contexts the live ruleset lists (none listed = refuse), each verified.
contexts="$(gh_ api "repos/$REPO/rules/branches/main" --jq \
  '.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context' \
  | LC_ALL=C sort -u)" || die 1 "cannot read the branch rules"
[ -n "$contexts" ] || die 4 "checks not green: the ruleset lists no required checks"

workflow_of() {
  case "$1" in
    check) echo ci.yml ;; scan) echo security.yml ;; images-gate) echo build-images.yml ;;
    docs-gate) echo docs.yml ;; ui-check) echo ui.yml ;; *) echo "" ;;
  esac
}
verify_check_run() {  # the job of that name in the newest pull_request run of its workflow, for this PR
  local name="$1" file wf run_id jobs jid rows
  file="$(workflow_of "$name")"
  wf="$(gh_ api "repos/$REPO/actions/workflows/$file/runs?head_sha=$sha&event=pull_request&per_page=100" --paginate \
    --jq ".workflow_runs[] | [.id, .run_attempt, .status, .head_sha, .path, .event, .repository.full_name, \
.head_repository.full_name, ([.pull_requests[]? | select(.number == $pr and .base.ref == \"main\")] | length | tostring)] | @tsv" \
    )" || die 4 "checks not green: cannot read the runs of $file"
  run_id="$(printf '%s\n' "$wf" | "$AWK" -F'\t' -v s="$sha" -v p=".github/workflows/$file" -v r="$REPO" \
    '$4 == s && $5 == p && $6 == "pull_request" && $7 == r && $8 == r && $9 != "0" { print $1 }' \
    | LC_ALL=C sort -rn | LC_ALL=C sed -n 1p)"
  [ -n "$run_id" ] || die 4 "checks not green: no pull_request run of $file for PR $pr on $sha"
  jobs="$(gh_ api "repos/$REPO/actions/runs/$run_id/jobs?filter=latest&per_page=100" --paginate \
    --jq '.jobs[] | [.id, .name, .status, (.conclusion // ""), .head_sha] | @tsv')" \
    || die 4 "checks not green: $name has no workflow job"
  rows="$(printf '%s\n' "$jobs" | "$AWK" -F'\t' -v n="$name" '$2 == n')"
  [ -n "$rows" ] || die 4 "checks not green: $name has no workflow job in run $run_id"
  [ -z "$(printf '%s\n' "$rows" | "$AWK" -F'\t' -v s="$sha" '!($3 == "completed" && $4 == "success" && $5 == s)')" ] \
    || die 4 "checks not green: $name in the newest run of $file on $sha"
  jid="$(tsv_field "$rows" 1)"
  [ -n "$(printf '%s\n' "$runs" | "$AWK" -F'\t' -v i="$jid" -v n="$name" \
    '$1 == i && $2 == n && $3 == "completed" && $4 == "success" && $5 == "github-actions" { print "ok" }')" ] \
    || die 4 "checks not green: $name has no successful check run for job $jid"
}
verify_gate_status() {  # the newest status of that context is a success created by the bot
  local gate
  gate="$(gh_ api "repos/$REPO/commits/$sha/statuses?per_page=100" --jq \
    "[.[] | select(.context == \"$1\")] | .[0] | [.state, .creator.login] | @tsv")" \
    || die 1 "cannot read the commit statuses of $sha"
  { [ "$(tsv_field "$gate" 1)" = success ] && [ "$(tsv_field "$gate" 2)" = 'pruefstand-bot[bot]' ]; } \
    || die 4 "checks not green: $1 is not a success set by pruefstand-bot on $sha"
}
runs="$(gh_ api "repos/$REPO/commits/$sha/check-runs?per_page=100" --paginate \
  --jq '.check_runs[] | [.id, .name, .status, (.conclusion // ""), (.app.slug // "")] | @tsv')" \
  || die 1 "cannot read the check runs of $sha"
while IFS= read -r ctx; do
  if [ -n "$(workflow_of "$ctx")" ]; then verify_check_run "$ctx"
  elif [ "$ctx" = "pruefstand/gate" ]; then verify_gate_status "$ctx"
  else die 4 "unverifiable required context: $ctx"; fi
done <<<"$contexts"

# 5. Re-read the head right before merging; the merge itself is pinned to <sha> as well.
[ "$(tsv_field "$(pr_state)" 4)" = "$sha" ] || die 5 "head changed while checking: not merging"
gh_ pr merge "$pr" --repo "$REPO" --squash --match-head-commit "$sha" || die 1 "merge failed"
gh_ pr comment "$pr" --repo "$REPO" --body "merged by lead: $sha; reviewer verdict: $verdict" \
  || echo "warning: merged, but the PR comment failed" >&2
echo "merged PR $pr at $sha"
