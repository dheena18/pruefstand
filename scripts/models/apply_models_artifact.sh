#!/usr/bin/env bash
# Applies the artefact of cassettes-models.yml (D900) to a working tree. The artefact is untrusted input:
#   1. only regular files and directories (no symlink, device, fifo) may exist in it;
#   2. SHA256SUMS.txt lists every file, every listed file exists and matches, no file is unlisted;
#   3. every path is on the result allow-list (no traversal) and within the size caps;
#   4. only then the listed files are installed one by one with mode 0644 (no tar, no exec bits).
# It commits nothing.
#   bash scripts/models/apply_models_artifact.sh <unzipped artefact dir> [repo root]
set -euo pipefail

src="${1:?usage: apply_models_artifact.sh <unzipped artefact dir> [repo root]}"
root="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
max_file=$((8 * 1024 * 1024))
max_total=$((64 * 1024 * 1024))
sums="$src/SHA256SUMS.txt"

fail() { echo "apply_models_artifact: $*" >&2; exit 1; }

[ -f "$sums" ] && [ ! -L "$sums" ] || fail "no regular SHA256SUMS.txt in $src"
if [ -n "$(find "$src" ! -type f ! -type d -print -quit)" ]; then
  fail "the artefact holds a symlink or another non-regular file"
fi
if grep -qvE '^[0-9a-f]{64}  \./[A-Za-z0-9_./-]+$' "$sums"; then
  fail "malformed line in SHA256SUMS.txt"
fi
(cd "$src" && sha256sum -c --quiet SHA256SUMS.txt) || fail "checksum mismatch"

listed="$(sed 's/^[0-9a-f]\{64\}  \.\///' "$sums" | LC_ALL=C sort)"
present="$(cd "$src" && find . -type f ! -path ./SHA256SUMS.txt | sed 's|^\./||' | LC_ALL=C sort)"
[ "$listed" = "$present" ] || fail "files in the artefact and in SHA256SUMS.txt differ (unlisted file?)"

total=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in *..* | /* | -*) fail "unsafe path in the artefact: $path" ;; esac
  case "$path" in
    packages/pruefstand/tests/cassettes/dataset/*.json | packages/pruefstand/tests/cassettes/perturb/*.json) ;;
    experiments/model_selection/indomain_dev.jsonl | experiments/model_selection/indomain_dev_checks.jsonl) ;;
    experiments/model_selection/indomain_dev_sources.json | experiments/model_selection/indomain_dev_card.md) ;;
    data/raw/indomain_dev_cache/*.json) ;;
    *) fail "unexpected path in the artefact: $path" ;;
  esac
  size="$(stat -c %s "$src/$path")"
  [ "$size" -le "$max_file" ] || fail "file larger than $max_file bytes: $path"
  total=$((total + size))
  [ "$total" -le "$max_total" ] || fail "artefact larger than $max_total bytes"
done <<< "$listed"

while IFS= read -r path; do
  [ -n "$path" ] || continue
  install -D -m 0644 "$src/$path" "$root/$path"
done <<< "$listed"
echo "applied $(wc -l < "$sums") files to $root (data/raw is git-ignored; nothing is committed)"
