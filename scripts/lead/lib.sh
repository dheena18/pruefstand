# Shared helpers of the lead scripts (sourced, never executed). D1230.
# shellcheck shell=bash
# Tools are resolved ONCE from the caller's PATH, then PATH is fixed, so nothing under $HOME shadows a system
# tool later. gh and git under $HOME are refused (uv legitimately lives in ~/.local/bin).

lead_die() { echo "$2" >&2; exit "$1"; }

_resolve() { local p; p="$(command -v "$1" 2>/dev/null)" || return 1; readlink -f "$p"; }
GH_BIN="$(_resolve gh || true)"; GIT_BIN="$(_resolve git || true)"; PY_BIN="$(_resolve python3 || true)"
UV_BIN="$(_resolve uv || true)"; [ -n "$UV_BIN" ] || UV_BIN="${HOME:-/nonexistent}/.local/bin/uv"
export PATH=/usr/local/bin:/usr/bin:/bin
_under_home() { case "$1" in "${HOME:-/nonexistent-home}"/*) return 0 ;; *) return 1 ;; esac; }
[ -n "$GIT_BIN" ] || lead_die 1 "git not found"
_under_home "$GIT_BIN" && lead_die 1 "refusing a git under HOME"
git() { "$GIT_BIN" "$@"; }
uv() { "$UV_BIN" "$@"; }
require_gh() {
  [ -n "$GH_BIN" ] || lead_die 1 "gh not found"
  _under_home "$GH_BIN" && lead_die 1 "refusing a gh under HOME"
  return 0
}
gh_() {
  require_gh
  env -u GITHUB_TOKEN -u GH_TOKEN "$GH_BIN" "$@"
}

abspath() {  # absolute path of an existing file, from any cwd
  local d
  d="$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s\n' "$d" "$(basename "$1")"
}

# Owner rule: no Claude-Session line and no "Generated with/by Claude Code" footer (case and spacing tolerant).
_FOOTER_RE='(Claude[[:space:]_-]*Session[[:space:]]*:|Generated[[:space:]]+(with|by)[[:space:]]+\[?[[:space:]]*Claude[[:space:]]+Code)'
forbid_stdin() {  # <label>; text on stdin
  if grep -Eiq "$_FOOTER_RE"; then
    lead_die 2 "REFUSED: $1 contains a Claude-Session line or a 'Generated with Claude Code' footer (owner rule)"
  fi
}
forbid_footer() {  # <file>
  [ -f "$1" ] || lead_die 2 "no such file: $1"
  forbid_stdin "$1" <"$1"
}

valid_branch() {  # no leading + or -, no refspec characters
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] && git check-ref-format --branch "$1" >/dev/null 2>&1
}

require_branch() {  # the worktree must be on <branch>, and never on main
  local cur
  valid_branch "$1" || lead_die 2 "invalid branch name: $1"
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

_secret_name() {  # basename -> 0 when it looks like a secret
  case "$1" in
    .env.example|.env.sample|.env.template) return 1 ;;
    .env|.env.*|*.pem|*.key|*.p12|*.pfx|*.kdbx|id_rsa*|id_dsa*|id_ecdsa*|id_ed25519*|credentials.json) return 0 ;;
  esac
  return 1
}

_stage_and_check() {  # stage into the CURRENT index, then refuse leftovers and risky files (exit 2)
  local f size bad=()
  git add -u
  if [ "${#ADD_PATHS[@]}" -gt 0 ]; then git add -- "${ADD_PATHS[@]}" || lead_die 2 "cannot add: ${ADD_PATHS[*]}"; fi
  mapfile -t leftovers < <(git ls-files --others --exclude-standard)
  if [ "${#leftovers[@]}" -gt 0 ]; then
    echo "REFUSED: untracked files are not staged. Pass --add <path> for the ones that belong in the commit, or remove/ignore the rest:" >&2
    printf '  %s\n' "${leftovers[@]}" >&2
    exit 2
  fi
  while IFS= read -r -d '' f; do
    size="$(git cat-file -s ":$f" 2>/dev/null || echo 0)"
    if [ "$size" -gt 1048576 ]; then bad+=("$f (larger than 1 MB)"); fi
    if _secret_name "${f##*/}"; then bad+=("$f (looks like a secret)"); fi
  done < <(git diff --cached --name-only -z --diff-filter=AM)
  if [ "${#bad[@]}" -gt 0 ]; then
    echo "REFUSED: staged files that must not be committed:" >&2
    printf '  %s\n' "${bad[@]}" >&2
    exit 2
  fi
}

check_staging() {  # the checks of _stage_and_check on a COPY of the index: the real index is never touched
  local idx rc
  idx="$(mktemp)" || lead_die 1 "mktemp failed"
  cp "$(git rev-parse --git-path index)" "$idx" 2>/dev/null || rm -f "$idx"
  (export GIT_INDEX_FILE="$idx"; _stage_and_check)
  rc=$?
  rm -f "$idx"
  return "$rc"
}

stage_changes() {  # tracked changes + explicit --add paths; a refusal leaves the index as it was
  check_staging || exit 2
  git add -u
  if [ "${#ADD_PATHS[@]}" -gt 0 ]; then git add -- "${ADD_PATHS[@]}"; fi
}

check_branch_messages() {  # the messages of exactly the commits a push would send (not yet on any origin ref)
  forbid_stdin "a commit message that is not on origin yet (nothing was pushed; fix it with git commit --amend or an interactive rebase)" \
    < <(git log --format=%B HEAD --not --remotes=origin)
}

commit_all() {  # <msgfile>: stage, commit, re-check the messages before anything is pushed
  stage_changes
  if git diff --cached --quiet; then
    echo "nothing staged (already committed?)"
  else
    git commit -q -F "$1" || { echo COMMIT_FAIL; exit 1; }
  fi
  check_branch_messages
}

push_branch() {  # plain push of exactly this branch, never forced
  local out
  out="$(mktemp)" || lead_die 1 "mktemp failed"
  if ! git push -q -u origin "refs/heads/$1:refs/heads/$1" >"$out" 2>&1; then echo PUSH_FAIL; tail -3 "$out"; rm -f "$out"; exit 1; fi
  rm -f "$out"
}

parse_common() {  # sets dry, ADD_PATHS and REST from the leading options
  dry=0; ADD_PATHS=(); REST=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run) dry=1; shift ;;
      --add) [ "$#" -ge 2 ] || lead_die 2 "--add needs a path"; ADD_PATHS+=("$2"); shift 2 ;;
      --) shift; REST+=("$@"); break ;;
      *) REST+=("$1"); shift ;;
    esac
  done
}
