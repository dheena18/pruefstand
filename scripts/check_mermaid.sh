#!/usr/bin/env bash
# Render every fenced `mermaid` block under docs/ with a pinned mermaid-cli (T0.4 S6b, A8-20, R9-26).
# A parse error fails the run and names the file and the line of the block. Not part of `make docs`.
# Known failure: a statement-ending ";" inside a sequence/state diagram label (use "," instead).
# Test hooks: MERMAID_DOCS_DIR (default docs), MERMAID_EXTRACT_ONLY=1 (print "<n>TAB<file:line>TAB<block>").
set -euo pipefail

# Local installs are floating (no lockfile for mermaid-cli); CI runs it on a read-only token, no secrets.
MERMAID_CLI_VERSION=11.17.0
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
docs_dir=${MERMAID_DOCS_DIR:-docs}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Extract one file per block ("<n>.mmd") and an index line "<n><TAB><file>:<line>". The counter n lives in
# this shell and is handed to every awk run, so blocks of different files never share a name. A fence is
# closed only by a fence of the same character and at least the same length, so a mermaid fence shown
# inside a longer fence is not extracted.
cd "$root"
n=0
: > "$work/index.tsv"
while IFS= read -r -d '' file; do
  n=$(awk -v work="$work" -v file="$file" -v start="$n" '
    function fence_len(line,   s, c, i) {
      s = line; sub(/^[ \t]+/, "", s); c = substr(s, 1, 1)
      if (c != "`" && c != "~") return 0
      for (i = 1; substr(s, i, 1) == c; i++) { }
      return i - 1
    }
    function fence_char(line,   s) { s = line; sub(/^[ \t]+/, "", s); return substr(s, 1, 1) }
    BEGIN { n = start }
    {
      sub(/\r$/, "")
      len = fence_len($0)
      if (!fenced) {
        if (len >= 3) {
          fenced = 1; fchar = fence_char($0); flen = len; mermaid = 0; open_at = FNR
          info = $0; sub(/^[ \t]*[`~]+[ \t]*/, "", info); sub(/[ \t]+$/, "", info)
          if (info == "mermaid") {
            mermaid = 1; n++; out = work "/" n ".mmd"
            printf "%d\t%s:%d\n", n, file, FNR + 1 >> (work "/index.tsv")
            printf "" > out
          }
        }
        next
      }
      rest = $0; sub(/^[ \t]+/, "", rest); gsub(/[`~]/, "", rest)
      if (len >= flen && fence_char($0) == fchar && rest ~ /^[ \t]*$/) {
        fenced = 0
        if (mermaid) close(out)
        next
      }
      if (mermaid) print > out
    }
    END {
      if (fenced) {
        printf "check_mermaid: %s:%d: unterminated code fence\n", file, open_at > "/dev/stderr"
        print "UNTERMINATED"
        exit 1
      }
      print n
    }
  ' "$file") || { echo "check_mermaid: stopping, $file has an unterminated fence" >&2; exit 1; }
done < <(find "$docs_dir" -name '*.md' -print0 | sort -z)

if [ "$n" -eq 0 ]; then
  echo "check_mermaid: no mermaid blocks found under $docs_dir" >&2
  exit 1
fi

if [ "${MERMAID_EXTRACT_ONLY:-}" = 1 ]; then
  while IFS=$'\t' read -r i where; do
    printf '%s\t%s\t%s\n' "$i" "$where" "$(sed ':a;N;$!ba;s/\n/\\n/g' "$work/$i.mmd")\\n"
  done < "$work/index.tsv"
  exit 0
fi

printf '{"args": ["--no-sandbox", "--disable-setuid-sandbox"]}\n' > "$work/puppeteer.json"
failed=0
total=0
while IFS=$'\t' read -r i where; do
  total=$((total + 1))
  if ! npx --yes "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}" -q \
    -p "$work/puppeteer.json" -i "$work/$i.mmd" -o "$work/$i.svg" > "$work/$i.log" 2>&1; then
    echo "check_mermaid: $where: mermaid parse error" >&2
    head -n 8 "$work/$i.log" | sed 's/^/    /' >&2
    failed=$((failed + 1))
  fi
done < "$work/index.tsv"
echo "check_mermaid: $total blocks rendered, $failed failed"
[ "$failed" -eq 0 ]
