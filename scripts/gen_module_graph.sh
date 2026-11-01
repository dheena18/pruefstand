#!/usr/bin/env bash
# Render the import graph of the pruefstand package to <out_dir>/module-deps.svg (T0.4 S4).
# Deterministic flags only: same sources in, byte-identical SVG out. Needs graphviz (`dot`).
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <out_dir>" >&2
  exit 2
fi
out_dir=$(realpath -m -- "$1")
mkdir -p "$out_dir"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONHASHSEED=0
exec uv run pydeps pruefstand --max-bacon 2 --cluster --rankdir TB --noshow \
  -o "$out_dir/module-deps.svg"
