#!/usr/bin/env bash
# verify_reviewed_tree <repo-root>: act only on reviewed code (T3.1a, confused-deputy guard). Sourced by the installer
# and the deploy; also runnable: `bash lib/git_verify.sh <repo-root>`.
#
# Both scripts run with powers the working tree must not be able to borrow (root through sudo; the cluster key of
# user pruefstand). So they proceed only if infra/gpu, infra/cluster, mk and the Makefile equal origin/main (no local
# edit, staged or not), nothing untracked or ignored sits under infra/gpu and infra/cluster (apart from __pycache__),
# and HEAD is contained in origin/main. As the owner it runs `git fetch origin` first; as root it never fetches (that
# would leave root-owned files in the owner's .git) and instead requires a fetch from the last 10 minutes
# (.git/FETCH_HEAD). It prints the commit it accepted. A tree without .git (a `git archive origin/main` export, which
# is what `make gpu-deploy-bin` and `make gpu-install-wrapper` use) is skipped: it holds exactly the committed files.
# Limit: this check lives in the same tree it checks; run the installer from a checkout you have not let agents edit
# (the make targets export origin/main instead of using the working tree).

_GV_PATHS=(infra/gpu infra/cluster mk Makefile)

_gv_die() {
  echo "git_verify: $1" >&2
  exit 1
}

verify_reviewed_tree() { # repo-root
  local repo="$1" stale
  local -a git=(git -c "safe.directory=$repo" -C "$repo")
  if ! [ -e "$repo/.git" ]; then
    echo "exported tree without .git: nothing to compare (commit: $(cat "$repo/COMMIT" 2>/dev/null || echo unknown))"
    return 0
  fi
  if [ "$(id -u)" -eq 0 ]; then
    stale="$(find "$repo/.git/FETCH_HEAD" -mmin -10 2>/dev/null || true)"
    if [ -z "$stale" ]; then
      _gv_die "run 'git fetch origin' as yourself first (root does not fetch: it would leave root-owned files in your .git)"
    fi
  elif ! "${git[@]}" fetch -q origin; then
    _gv_die "git fetch origin failed"
  fi
  if ! "${git[@]}" rev-parse --verify -q origin/main >/dev/null; then _gv_die "origin/main is unknown"; fi
  if ! "${git[@]}" diff --quiet origin/main -- "${_GV_PATHS[@]}"; then
    _gv_die "${_GV_PATHS[*]} differ from origin/main (edited, staged or committed locally): refusing"
  fi
  if [ -n "$("${git[@]}" ls-files --others --exclude-standard -- infra/gpu infra/cluster)" ]; then
    _gv_die "untracked files under infra/gpu or infra/cluster: refusing (origin/main has none)"
  fi
  if "${git[@]}" ls-files --others --ignored --exclude-standard -- infra/gpu infra/cluster | grep -qv '__pycache__/'; then
    _gv_die "ignored files under infra/gpu or infra/cluster: refusing"
  fi
  if ! "${git[@]}" merge-base --is-ancestor HEAD origin/main; then
    _gv_die "HEAD is not contained in origin/main: refusing"
  fi
  echo "reviewed tree: commit $("${git[@]}" rev-parse HEAD)"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  verify_reviewed_tree "${1:?usage: git_verify.sh <repo-root>}"
fi
