#!/usr/bin/env bash
# sync_executor.sh <tag> [--init] [--dry-run] (T6.2a S10, D1085, D1266): copy the executor code of this
# public repo at an annotated maintainer tag `executor-<YYYYMMDD>[.N]` on `main` into a clone of the
# private executor repo and open a PR there. Maintainer-run only (the owner's laptop): it needs access to
# the private repo, which the VM token does not have. `v*` tags belong to the release App and are refused
# like any other ref.
#
# Synced: infra/gate-executor/{orchestrator,llm-proxy,host} (same paths), infra/gate-executor/workflows/*.yml
# (to .github/workflows/ in the private repo, where they run) and the files of
# infra/gate-executor/private-repo-template/ (to the private repo root: README.md, .gitignore). Everything
# else in the private repo (canaries, state, baselines index) is left alone. `SYNCED_FROM` records
# "<tag> <commit>".
#
# --init: first fill of the EMPTY private repo: commits on `main` and pushes it directly (there is no base
# branch for a PR yet); refused when the private repo already has any branch.
#
# Env: PRIVATE_REPO (default dheena18/pruefstand-gate), PRIVATE_REMOTE (clone URL, default
# https://github.com/$PRIVATE_REPO.git), MAIN_REF (default origin/main).
# Exit: 0 ok, 1 git/gh failure, 2 refused (tag name, lightweight tag, not on main, --init on a non-empty
# repo), 64 usage.
set -euo pipefail

die() { echo "sync_executor: $1" >&2; exit "${2:-1}"; }
usage="usage: sync_executor.sh <executor-YYYYMMDD[.N]> [--init] [--dry-run]"

[ "$#" -ge 1 ] && [ "$#" -le 3 ] || die "$usage" 64
tag="$1"
shift
dry_run=0
init=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --init) init=1 ;;
    *) die "$usage" 64 ;;
  esac
done
private_repo="${PRIVATE_REPO:-dheena18/pruefstand-gate}"
private_remote="${PRIVATE_REMOTE:-https://github.com/${private_repo}.git}"
main_ref="${MAIN_REF:-origin/main}"

[[ "$tag" =~ ^executor-[0-9]{8}(\.[0-9]+)?$ ]] || die "refused: only annotated executor-<YYYYMMDD>[.N] tags (got '$tag')" 2
[ "$(git cat-file -t "refs/tags/$tag" 2>/dev/null)" = "tag" ] || die "refused: $tag is not an annotated tag" 2
commit="$(git rev-parse "${tag}^{commit}")"
git merge-base --is-ancestor "$commit" "$main_ref" || die "refused: $tag ($commit) is not on main ($main_ref)" 2

if [ "$init" -eq 1 ] && [ -n "$(git ls-remote --heads "$private_remote")" ]; then
  die "refused: --init needs an empty private repo, $private_repo is not empty (sync without --init)" 2
fi

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
dest="$work/private"
if [ "$init" -eq 1 ]; then
  git init -q -b main "$dest"
  git -C "$dest" remote add origin "$private_remote"
  branch="main"
else
  git clone -q "$private_remote" "$dest"
  branch="sync/$tag"
  git -C "$dest" checkout -q -b "$branch"
fi

for dir in orchestrator llm-proxy host; do
  rm -rf -- "${dest:?}/infra/gate-executor/$dir"
  if git cat-file -e "${commit}:infra/gate-executor/$dir" 2>/dev/null; then
    git archive "$commit" "infra/gate-executor/$dir" | tar -x -C "$dest"
  fi
done
mkdir -p "$work/src"
for part in workflows private-repo-template; do
  if git cat-file -e "${commit}:infra/gate-executor/$part" 2>/dev/null; then
    git archive "$commit" "infra/gate-executor/$part" | tar -x -C "$work/src"
  fi
done
if compgen -G "$work/src/infra/gate-executor/workflows/*.yml" >/dev/null; then
  mkdir -p "$dest/.github/workflows"
  cp "$work"/src/infra/gate-executor/workflows/*.yml "$dest/.github/workflows/"
fi
if [ -d "$work/src/infra/gate-executor/private-repo-template" ]; then
  cp -R "$work/src/infra/gate-executor/private-repo-template/." "$dest/"
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
if [ "$init" -eq 1 ]; then
  echo "sync_executor: initial executor code pushed to $private_repo main"
  exit 0
fi
gh pr create --repo "$private_repo" --base main --head "$branch" \
  --title "sync: public $tag" \
  --body "Executor code of the public repo at \`$tag\` (\`$commit\`), copied by scripts/sync_executor.sh (T6.2a S10). Review the diff, then merge."
