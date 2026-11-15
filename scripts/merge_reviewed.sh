#!/usr/bin/env bash
# usage: scripts/merge_reviewed.sh <pr> <sha> <reviewer-verdict>   (verdict: third argument, or env REVIEW_VERDICT)
# Squash-merges PR <pr> (open, not draft, base main) only if
#   - this script and scripts/merge_paths.py are byte-identical to origin/main (else exit 3),
#   - the PR head is exactly <sha> (exit 5),
#   - the changes from the merge base to <sha> touch no owner-merge path (exit 3 "owner merge required"),
#   - every context the live ruleset requires (none = refuse) is verified on <sha>: check, scan, images-gate,
#     docs-gate, ui-check = a successful job of ci.yml / security.yml / build-images.yml / docs.yml / ui.yml
#     run by a pull_request event; pruefstand/gate = a success status set by pruefstand-bot[bot]; any other
#     context is unverifiable (exit 4).
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
ENV=/usr/bin/env; GIT=/usr/bin/git; PY=/usr/bin/python3; AWK=/usr/bin/awk; TR=/usr/bin/tr
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

# 1. The code that runs here must be the code on origin/main.
repo="$("$GIT" -C "$here" rev-parse --show-toplevel)" || die 1 "not inside a git checkout"
"$GIT" -C "$repo" fetch -q origin main || die 1 "cannot fetch origin main"
for f in merge_reviewed.sh merge_paths.py; do
  mine="$("$GIT" -C "$repo" hash-object -- "$here/$f")" || die 1 "cannot hash $f"
  main="$("$GIT" -C "$repo" rev-parse "origin/main:scripts/$f" 2>/dev/null)" || die 3 "script differs from origin/main ($f missing there)"
  [ "$mine" = "$main" ] || die 3 "script differs from origin/main: owner merge required"
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
"$GIT" -C "$repo" fetch -q origin main "$sha" || die 1 "cannot fetch $sha"
base="$("$GIT" -C "$repo" merge-base origin/main "$sha")" || die 1 "no merge base with origin/main"
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
verify_check_run() {  # a successful job of the expected workflow, run by a pull_request on <sha>
  local name="$1" file rows id status conclusion app job run
  file="$(workflow_of "$name")"
  rows="$(printf '%s\n' "$runs" | "$AWK" -F'\t' -v n="$name" '$2 == n')"
  [ -n "$rows" ] || die 4 "checks not green: $name missing on $sha"
  while IFS=$'\t' read -r id _ status conclusion app; do
    [ "$status" = completed ] && [ "$conclusion" = success ] && [ "$app" = github-actions ] \
      || die 4 "checks not green: $name on $sha"
    job="$(gh_ api "repos/$REPO/actions/jobs/$id" --jq '[.run_id, .name, .head_sha] | @tsv' 2>/dev/null)" \
      || die 4 "checks not green: $name has no workflow job"
    [ "$(tsv_field "$job" 2)" = "$name" ] && [ "$(tsv_field "$job" 3)" = "$sha" ] \
      || die 4 "checks not green: $name job does not match $sha"
    run="$(gh_ api "repos/$REPO/actions/runs/$(tsv_field "$job" 1)" --jq \
      '[.event, .head_sha, .path, .repository.full_name, .head_repository.full_name] | @tsv' 2>/dev/null)" \
      || die 4 "checks not green: $name has no workflow run"
    [ "$(tsv_field "$run" 1)" = pull_request ] && [ "$(tsv_field "$run" 2)" = "$sha" ] \
      && [ "$(tsv_field "$run" 3)" = ".github/workflows/$file" ] \
      && [ "$(tsv_field "$run" 4)" = "$REPO" ] && [ "$(tsv_field "$run" 5)" = "$REPO" ] \
      || die 4 "checks not green: $name is not a pull_request run of its workflow on $sha"
  done <<<"$rows"
}
verify_gate_status() {  # the newest status of that context is a success created by the bot
  local gate
  gate="$(gh_ api "repos/$REPO/commits/$sha/statuses?per_page=100" --jq \
    "[.[] | select(.context == \"$1\")] | .[0] | [.state, .creator.login] | @tsv")" \
    || die 1 "cannot read the commit statuses of $sha"
  { [ "$(tsv_field "$gate" 1)" = success ] && [ "$(tsv_field "$gate" 2)" = 'pruefstand-bot[bot]' ]; } \
    || die 4 "checks not green: $1 is not a success set by pruefstand-bot on $sha"
}
runs="$(gh_ api "repos/$REPO/commits/$sha/check-runs?filter=latest&per_page=100" --paginate \
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
