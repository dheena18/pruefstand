# Shared helpers of the lead scripts (sourced, never executed). D1230.
# shellcheck shell=bash
export PATH="$HOME/.local/bin:$PATH"

lead_die() { echo "$2" >&2; exit "$1"; }
gh_() { env -u GITHUB_TOKEN -u GH_TOKEN gh "$@"; }

abspath() {  # absolute path of an existing file, from any cwd
  local d
  d="$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s\n' "$d" "$(basename "$1")"
}

forbid_footer() {  # owner rule: no Claude-Session line, no "Generated with Claude Code" footer
  [ -f "$1" ] || lead_die 2 "no such file: $1"
  if grep -Eiq 'Claude-Session:|Generated with \[?Claude Code' "$1"; then
    lead_die 2 "REFUSED: $1 contains a Claude-Session line or a 'Generated with Claude Code' footer (owner rule)"
  fi
}

require_branch() {  # the worktree must be on <branch>, and never on main
  local cur
  cur="$(git symbolic-ref --short -q HEAD)" || lead_die 2 "detached HEAD in $PWD"
  [ "$cur" = "$1" ] || lead_die 2 "worktree is on '$cur', not '$1'"
  case "$1" in main|master) lead_die 2 "refusing to work on $1" ;; esac
}

check_ruff() {  # ruff check + ruff format --check; prints the first lines of a failure
  local out
  out="$(mktemp)" || lead_die 1 "mktemp failed"
  if ! uv run ruff check --no-cache . >"$out" 2>&1; then echo RUFF_FAIL; head -8 "$out"; rm -f "$out"; exit 1; fi
  if ! uv run ruff format --check . >"$out" 2>&1; then echo FORMAT_FAIL; head -8 "$out"; rm -f "$out"; exit 1; fi
  rm -f "$out"
}

commit_all() {  # commit everything with the message file (if anything is staged)
  git add -A
  if ! git diff --cached --quiet; then
    git commit -q -F "$1" || { echo COMMIT_FAIL; exit 1; }
  else
    echo "nothing staged (already committed?)"
  fi
}

push_branch() {  # plain push, never forced
  local out
  out="$(mktemp)" || lead_die 1 "mktemp failed"
  if ! git push -q -u origin "$1" >"$out" 2>&1; then echo PUSH_FAIL; tail -3 "$out"; rm -f "$out"; exit 1; fi
  rm -f "$out"
}
