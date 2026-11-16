#!/usr/bin/env bash
# backup.sh --repo <dir> [--keep N] (T6.2b, X2.6, D156, Y5.5): the weekly encrypted backup of the gate
# executor, run by the private backup.yml on the A40 runner as user pruefstand.
#
# One stream = tar of (`git bundle create --all` of the private repo checkout, incl. canaries/heldout/ and
# every branch) + `$PRUEFSTAND_DATA_ROOT/baselines/`, encrypted as a WHOLE with `age -r "$AGE_RECIPIENT"`
# into `$PRUEFSTAND_DATA_ROOT/backups/<YYYY-MM-DD>/pruefstand-gate.bundle.tar.age` (written as *.partial,
# then renamed); the newest N dated backup directories are kept (default 8). No plaintext copy is kept:
# the bundle exists only in a private temp dir for the length of the run. The private key lives only
# on the owner's laptop. Env: AGE_RECIPIENT (the owner's age public key, Actions variable),
# PRUEFSTAND_DATA_ROOT (runner.env).
# Exit: 0 ok, 1 failure (data root unusable, git/age/tar error), 2 refused (bad recipient), 64 usage.
set -euo pipefail
umask 077

die() { echo "backup: $1" >&2; exit "${2:-1}"; }
usage="usage: backup.sh --repo <dir> [--keep N]"
repo=""
keep=8
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$#" -ge 2 ] || die "$usage" 64; repo="$2"; shift 2 ;;
    --keep) [ "$#" -ge 2 ] || die "$usage" 64; keep="$2"; shift 2 ;;
    *) die "$usage" 64 ;;
  esac
done
[ -n "$repo" ] || die "$usage" 64
[[ "$keep" =~ ^[1-9][0-9]?$ ]] || die "--keep must be 1..99" 64
[[ "${AGE_RECIPIENT:-}" =~ ^age1[0-9a-z]{58}$ ]] || die "refused: AGE_RECIPIENT is not an age public key (age1...)" 2
root="${PRUEFSTAND_DATA_ROOT:-}"
[ -n "$root" ] && [ -d "$root" ] && [ -w "$root" ] || die "data root unusable: PRUEFSTAND_DATA_ROOT" 1
command -v age >/dev/null || die "age is not installed" 1

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
git -C "$repo" bundle create "$tmp/pruefstand-gate.bundle" --all
members=(-C "$tmp" pruefstand-gate.bundle)
if [ -d "$root/baselines" ]; then
  members+=(-C "$root" baselines)
else
  echo "backup: warning: $root/baselines does not exist; bundle only" >&2
fi

dest="$root/backups/$(date -u +%Y-%m-%d)"
mkdir -p "$dest"
out="$dest/pruefstand-gate.bundle.tar.age"
tar -cf - "${members[@]}" | age -r "$AGE_RECIPIENT" -o "$out.partial"
mv -f -- "$out.partial" "$out"
echo "backup: wrote $out sha256 $(sha256sum "$out" | cut -d' ' -f1)"

# keep the newest $keep dated directories (names sort by date)
mapfile -t dated < <(find "$root/backups" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
  -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}' -printf '%f\n' | sort -r)
for old in "${dated[@]:$keep}"; do
  rm -rf -- "${root:?}/backups/$old"
  echo "backup: pruned $old"
done
