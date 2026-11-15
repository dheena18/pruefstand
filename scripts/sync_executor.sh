#!/usr/bin/env bash
# sync_executor.sh <tag> [--dry-run] (T6.2a S10, D1085): copy the executor code of this public repo at an
# annotated maintainer tag `executor-<YYYYMMDD>[.N]` on `main` into a clone of the private executor repo
# and open a PR there. Maintainer-run only: it needs access to the private repo, which the VM token does
# not have. `v*` tags belong to the release App and are refused like any other ref.
#
# Synced: infra/gate-executor/{orchestrator,llm-proxy,host} (same paths) and infra/gate-executor/workflows/*
# (to .github/workflows/ in the private repo, where they run). Everything else in the private repo
# (canaries, state, baselines index) is left alone. A file `SYNCED_FROM` records "<tag> <commit>".
#
# Env: PRIVATE_REPO (default dheena18/pruefstand-gate), PRIVATE_REMOTE (clone URL, default
# https://github.com/$PRIVATE_REPO.git), MAIN_REF (default origin/main).
# Exit: 0 ok, 1 git/gh failure, 2 refused (tag name, lightweight tag, not on main), 64 usage.
set -euo pipefail

die() { echo "sync_executor: $1" >&2; exit "${2:-1}"; }

[ "$#" -ge 1 ] && [ "$#" -le 2 ] || die "usage: sync_executor.sh <executor-YYYYMMDD[.N]> [--dry-run]" 64
tag="$1"
dry_run=0
if [ "$#" -eq 2 ]; then
  [ "$2" = "--dry-run" ] || die "usage: sync_executor.sh <executor-YYYYMMDD[.N]> [--dry-run]" 64
  dry_run=1
fi
private_repo="${PRIVATE_REPO:-dheena18/pruefstand-gate}"
private_remote="${PRIVATE_REMOTE:-https://github.com/${private_repo}.git}"
main_ref="${MAIN_REF:-origin/main}"

[[ "$tag" =~ ^executor-[0-9]{8}(\.[0-9]+)?$ ]] || die "refused: only annotated executor-<YYYYMMDD>[.N] tags (got '$tag')" 2
[ "$(git cat-file -t "refs/tags/$tag" 2>/dev/null)" = "tag" ] || die "refused: $tag is not an annotated tag" 2
commit="$(git rev-parse "${tag}^{commit}")"
git merge-base --is-ancestor "$commit" "$main_ref" || die "refused: $tag ($commit) is not on main ($main_ref)" 2

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
dest="$work/private"
git clone -q "$private_remote" "$dest"
branch="sync/$tag"
git -C "$dest" checkout -q -b "$branch"

for dir in orchestrator llm-proxy host; do
  rm -rf -- "${dest:?}/infra/gate-executor/$dir"
  if git cat-file -e "${commit}:infra/gate-executor/$dir" 2>/dev/null; then
    git archive "$commit" "infra/gate-executor/$dir" | tar -x -C "$dest"
  fi
done
if git cat-file -e "${commit}:infra/gate-executor/workflows" 2>/dev/null; then
  mkdir -p "$dest/.github/workflows"
  git archive "$commit" infra/gate-executor/workflows | tar -x -C "$work"
  cp "$work"/infra/gate-executor/workflows/* "$dest/.github/workflows/"
fi
printf '%s %s\n' "$tag" "$commit" > "$dest/SYNCED_FROM"

git -C "$dest" add -A
if git -C "$dest" diff --cached --quiet; then
  echo "sync_executor: nothing to sync for $tag"
  exit 0
fi
git -C "$dest" commit -q -m "sync: public $tag ($commit)"
git -C "$dest" show --stat --format='%s' HEAD
if [ "$dry_run" -eq 1 ]; then
  echo "sync_executor: dry run, nothing pushed"
  exit 0
fi
git -C "$dest" push -q origin "$branch"
gh pr create --repo "$private_repo" --base main --head "$branch" \
  --title "sync: public $tag" \
  --body "Executor code of the public repo at \`$tag\` (\`$commit\`), copied by scripts/sync_executor.sh (T6.2a S10). Review the diff, then merge."
