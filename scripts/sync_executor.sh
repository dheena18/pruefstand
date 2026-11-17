#!/usr/bin/env bash
# sync_executor.sh <tag> [--init] [--dry-run] (T6.2a S10, D1085, D1266): copy the executor code of this
# public repo at an annotated maintainer tag `executor-<YYYYMMDD>[.N]` on `main` into a clone of the
# private executor repo and open a PR there. Maintainer-run only (the owner's laptop): it needs access to
# the private repo, which the VM token does not have. `v*` tags belong to the release App and are refused
# like any other ref.
#
# Synced: infra/gate-executor/{orchestrator,llm-proxy,host} (same paths), infra/gate-executor/workflows/*.yml
# and *.yaml (replacing .github/workflows/ of the private repo as a whole, where they run; a tag without any
# workflow file is
# refused when the private repo has workflows) and the files of
# infra/gate-executor/private-repo-template/ (to the private repo root: README.md, .gitignore). Everything
# else in the private repo (canaries, state, baselines index) is left alone. `SYNCED_FROM` records
# "<tag> <commit>" and one "workflow <file>" line per synced workflow.
#
# --init: first fill of the EMPTY private repo: commits on `main` and pushes it directly (there is no base
# branch for a PR yet); refused when the private repo already has any branch.
#
# Env: PRIVATE_REPO (default dheena18/pruefstand-gate), PRIVATE_REMOTE (clone URL, default
# https://github.com/$PRIVATE_REPO.git), MAIN_REF (default origin/main).
# Exit: 0 ok, 1 git/gh failure (incl. an unreachable private repo), 2 refused (tag name, lightweight tag, not on main, --init on a non-empty
# repo), 64 usage.
set -euo pipefail

die() { echo "sync_executor: $1" >&2; exit "${2:-1}"; }
VM_STEP="sudo -u pruefstand git -C /home/pruefstand/pruefstand-gate pull --ff-only"
# Every successful run ends with the step on the VM that brings the executor's checkout up to date.
done_ok() {
  echo "sync_executor: $1"
  echo "Then, on the VM (once the private main has the change): $VM_STEP"
  exit 0
}
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

if [ "$init" -eq 1 ]; then
  heads="$(git ls-remote --heads "$private_remote")" || die "cannot reach $private_remote (--init needs it)" 1
  [ -z "$heads" ] || die "refused: --init needs an empty private repo, $private_repo is not empty (sync without --init)" 2
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
# .github/workflows is replaced as a WHOLE, so a workflow retired in the public repo stops running here;
# a source without any *.yml / *.yaml never wipes the private workflows (refused) and is skipped on a first fill.
shopt -s nullglob
sources=("$work"/src/infra/gate-executor/workflows/*.yml "$work"/src/infra/gate-executor/workflows/*.yaml)
shopt -u nullglob
listing=""
if [ "${#sources[@]}" -gt 0 ]; then
  rm -rf -- "${dest:?}/.github/workflows"
  mkdir -p "$dest/.github/workflows"
  cp "${sources[@]}" "$dest/.github/workflows/"
  for wf in "${sources[@]}"; do listing+="workflow ${wf##*/}"$'\n'; done
  # D1095: a workflow that calls a gate-orchestrator subcommand the tag's CLI does not define is refused
  cli="$dest/infra/gate-executor/orchestrator/gate_orchestrator/cli.py"
  wanted="$(grep -ohE '(gate-orchestrator|-m gate_orchestrator) [a-z][a-z-]*' "${sources[@]}" | awk '{print $NF}' | sort -u || true)"
  for sub in $wanted; do
    grep -qF "add_parser(\"$sub\"" "$cli" 2>/dev/null \
      || die "refused: the workflows call gate-orchestrator $sub, which $tag does not provide (D1095)" 2
  done
elif compgen -G "$dest/.github/workflows/*" >/dev/null; then
  die "refused: $tag has no *.yml or *.yaml in infra/gate-executor/workflows; the private workflows would all be removed" 2
fi
if [ -d "$work/src/infra/gate-executor/private-repo-template" ]; then
  cp -R "$work/src/infra/gate-executor/private-repo-template/." "$dest/"
fi
printf '%s %s\n%s' "$tag" "$commit" "$listing" > "$dest/SYNCED_FROM"

git -C "$dest" add -A
# File modes come from the public tree, never from the clone's filesystem: with core.fileMode=false
# (Windows Git Bash) a plain `git add` stores the executable host scripts as 100644.
for dir in orchestrator llm-proxy host; do
  git ls-tree -r "$commit" -- "infra/gate-executor/$dir" | while read -r mode _ _ path; do
    case "$mode" in
      100755) git -C "$dest" update-index --chmod=+x -- "$path" ;;
      100644) git -C "$dest" update-index --chmod=-x -- "$path" ;;
    esac
  done
done
if git -C "$dest" diff --cached --quiet; then
  done_ok "nothing to sync for $tag"
fi
git -C "$dest" commit -q -m "sync: public $tag ($commit)"
git -C "$dest" show --stat --format='%s' HEAD
if [ "$dry_run" -eq 1 ]; then
  done_ok "dry run, nothing pushed"
fi
git -C "$dest" push -q origin "$branch"
if [ "$init" -eq 1 ]; then
  done_ok "initial executor code pushed to main of $private_remote"
fi
gh pr create --repo "$private_repo" --base main --head "$branch" \
  --title "sync: public $tag" \
  --body "Executor code of the public repo at \`$tag\` (\`$commit\`), copied by scripts/sync_executor.sh (T6.2a S10). Review the diff, then merge."
done_ok "PR opened in $private_repo; review and merge it there"
