#!/usr/bin/env bash
# build_set.sh <populated|empty> [--out <name>]: build one fixture set into apps/dashboard/.sets/<name>/
# (ui-spec §2.4). NEXT_PUBLIC_* and NEXT_BASE_PATH are inlined at build time, so a different env needs a
# different --out (T8.4's populated-try builds). Writes the header-free serve.json for `serve` / Playwright.
set -euo pipefail

set_name="${1:-}"
case "$set_name" in
  populated | empty) shift ;;
  *) echo "usage: build_set.sh <populated|empty> [--out <name>]" >&2; exit 2 ;;
esac
out_name="$set_name"
if [ "${1:-}" = "--out" ]; then
  out_name="${2:?--out needs a name}"
fi

root="$(cd "$(dirname "$0")/../.." && pwd)"
app="$root/apps/dashboard"
(cd "$app" && DASHBOARD_DATA_DIR="$app/fixtures/$set_name" pnpm build)

rm -rf "$app/.sets/$out_name"
mkdir -p "$app/.sets"
mv "$app/out" "$app/.sets/$out_name"
printf '{"cleanUrls": false, "trailingSlash": true}\n' > "$app/.sets/$out_name/serve.json"
echo "build_set: apps/dashboard/.sets/$out_name"
