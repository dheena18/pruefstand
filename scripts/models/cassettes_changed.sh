#!/usr/bin/env bash
# Prints `changed=true` when anything under the cassette directory differs from HEAD (modified,
# deleted or new files), else `changed=false`. Fails closed: a git failure exits non-zero and
# prints nothing. Used by cassettes.yml (T1.4); tested in
# scripts/models/tests/test_cassette_changes.py. Run it from the repository root.
set -euo pipefail

DIR="${1:-packages/pruefstand/tests/cassettes}"
out="$(git status --porcelain --untracked-files=all -- "$DIR")"
if [ -n "$out" ]; then
  echo "changed=true"
else
  echo "changed=false"
fi
