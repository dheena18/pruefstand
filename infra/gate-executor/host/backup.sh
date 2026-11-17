#!/usr/bin/env bash
# backup.sh --repo <dir> [--keep N] [--dry-run] (T6.2b, X2.6, D156, Y5.5): the weekly encrypted backup of the gate
# executor, run by the private backup.yml on the A40 runner as user pruefstand.
#
# One stream = tar of (`git bundle create --all` of the private repo checkout, incl. canaries/heldout/ and
# every branch) + `$PRUEFSTAND_DATA_ROOT/baselines/`, encrypted as a WHOLE with `age -r "$AGE_RECIPIENT"`
# into `$PRUEFSTAND_DATA_ROOT/backups/<YYYY-MM-DD>/pruefstand-gate.bundle.tar.age` (written as *.partial,
# then renamed); the newest N dated backup directories are kept (default 8). No plaintext copy is kept:
# the bundle exists only in a private temp dir for the length of the run. The private key lives only
# on the owner's laptop. Env: AGE_RECIPIENT (the owner's age public key, Actions variable),
# PRUEFSTAND_DATA_ROOT (runner.env). --dry-run checks the inputs and prints the pipeline, writing nothing.
# Exit: 0 ok, 1 failure (data root unusable, git/age/tar error), 2 refused (bad recipient), 64 usage.
set -euo pipefail
umask 077

die() { echo "backup: $1" >&2; exit "${2:-1}"; }
usage="usage: backup.sh --repo <dir> [--keep N] [--dry-run]"
repo=""
keep=8
dry_run=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$#" -ge 2 ] || die "$usage" 64; repo="$2"; shift 2 ;;
    --keep) [ "$#" -ge 2 ] || die "$usage" 64; keep="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    *) die "$usage" 64 ;;
  esac
done
[ -n "$repo" ] || die "$usage" 64
[[ "$keep" =~ ^[1-9][0-9]?$ ]] || die "--keep must be 1..99" 64
[[ "${AGE_RECIPIENT:-}" =~ ^age1[0-9a-z]{58}$ ]] || die "refused: AGE_RECIPIENT is not an age public key (age1...)" 2
root="${PRUEFSTAND_DATA_ROOT:-}"
[ -n "$root" ] && [ -d "$root" ] && [ -w "$root" ] || die "data root unusable: PRUEFSTAND_DATA_ROOT" 1
dest="$root/backups/$(date -u +%Y-%m-%d)"
out="$dest/pruefstand-gate.bundle.tar.age"
if [ "$dry_run" -eq 1 ]; then
  echo "git -C $repo bundle create <private tmp>/pruefstand-gate.bundle --all"
  echo "tar -cf - -C <private tmp> pruefstand-gate.bundle -C $root baselines | age -r $AGE_RECIPIENT -o $out.partial"
  echo "mv -f -- $out.partial $out"
  echo "keep the newest $keep dated directories of $root/backups"
  exit 0
fi
command -v age >/dev/null || die "age is not installed" 1

tmp="$(mktemp -d)"
partial=""
trap 'rm -rf -- "$tmp"; [ -z "$partial" ] || rm -f -- "$partial"' EXIT
git -C "$repo" bundle create "$tmp/pruefstand-gate.bundle" --all
members=(-C "$tmp" pruefstand-gate.bundle)
if [ -d "$root/baselines" ]; then
  members+=(-C "$root" baselines)
else
  echo "backup: warning: $root/baselines does not exist; bundle only" >&2
fi

mkdir -p "$dest"
partial="$out.partial"  # removed by the EXIT trap if tar or age fails (review #214)
tar -cf - "${members[@]}" | age -r "$AGE_RECIPIENT" -o "$partial"
mv -f -- "$partial" "$out"
partial=""
echo "backup: wrote $out sha256 $(sha256sum "$out" | cut -d' ' -f1)"

# keep the newest $keep dated directories (names sort by date)
mapfile -t dated < <(find "$root/backups" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended \
  -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}' -printf '%f\n' | sort -r)
for old in "${dated[@]:$keep}"; do
  rm -rf -- "${root:?}/backups/$old"
  echo "backup: pruned $old"
done
