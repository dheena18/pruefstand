#!/usr/bin/env bash
# Applies the artefact of cassettes-models.yml (D900) to a working tree: verifies SHA256SUMS.txt, accepts only the
# known result locations, then copies the files to the repository root. It commits nothing.
#   bash scripts/models/apply_models_artifact.sh <unzipped artefact dir> [repo root]
set -euo pipefail

src="${1:?usage: apply_models_artifact.sh <unzipped artefact dir> [repo root]}"
root="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
[ -f "$src/SHA256SUMS.txt" ] || { echo "no SHA256SUMS.txt in $src" >&2; exit 1; }
(cd "$src" && sha256sum -c --quiet SHA256SUMS.txt)
while read -r _ path; do
  path="${path#./}"
  case "$path" in *..* | /* | -*) echo "unsafe path in the artefact: $path" >&2; exit 1 ;; esac
  case "$path" in
    packages/pruefstand/tests/cassettes/dataset/*.json | packages/pruefstand/tests/cassettes/perturb/*.json) ;;
    experiments/model_selection/indomain_dev.jsonl | experiments/model_selection/indomain_dev_checks.jsonl) ;;
    experiments/model_selection/indomain_dev_sources.json | experiments/model_selection/indomain_dev_card.md) ;;
    data/raw/indomain_dev_cache/*.json) ;;
    *) echo "unexpected path in the artefact: $path" >&2; exit 1 ;;
  esac
done < "$src/SHA256SUMS.txt"
(cd "$src" && tar -cf - --exclude=./SHA256SUMS.txt .) | tar -xf - -C "$root"
echo "applied $(wc -l < "$src/SHA256SUMS.txt") files to $root (data/raw is git-ignored; nothing is committed)"
