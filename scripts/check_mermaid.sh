#!/usr/bin/env bash
# Render every fenced `mermaid` block under docs/ with a pinned mermaid-cli (T0.4 S6b, A8-20, R9-26).
# A parse error fails the run and names the file and the line of the block. Not part of `make docs`.
# Known failure: a statement-ending ";" inside a sequence/state diagram label (use "," instead).
set -euo pipefail

MERMAID_CLI_VERSION=11.17.0
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Extract: one file per block ("<n>.mmd") and an index line "<n><TAB><file>:<line>".
cd "$root"
find docs -name '*.md' -print0 | sort -z | xargs -0 awk -v work="$work" '
  FNR == 1 { open = 0 }
  !open && /^[[:space:]]*```mermaid[[:space:]]*$/ { open = 1; n++; out = work "/" n ".mmd"; printf "%d\t%s:%d\n", n, FILENAME, FNR + 1 >> (work "/index.tsv"); next }
  open && /^[[:space:]]*```[[:space:]]*$/ { open = 0; close(out); next }
  open { print > out }
'
if [ ! -s "$work/index.tsv" ]; then
  echo "check_mermaid: no mermaid blocks found under docs/" >&2
  exit 1
fi
printf '{"args": ["--no-sandbox", "--disable-setuid-sandbox"]}\n' > "$work/puppeteer.json"

failed=0
total=0
while IFS=$'\t' read -r n where; do
  total=$((total + 1))
  if ! npx --yes "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}" -q \
    -p "$work/puppeteer.json" -i "$work/$n.mmd" -o "$work/$n.svg" > "$work/$n.log" 2>&1; then
    echo "check_mermaid: $where: mermaid parse error" >&2
    head -n 8 "$work/$n.log" | sed 's/^/    /' >&2
    failed=$((failed + 1))
  fi
done < "$work/index.tsv"
echo "check_mermaid: $total blocks rendered, $failed failed"
[ "$failed" -eq 0 ]
