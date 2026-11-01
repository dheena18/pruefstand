#!/usr/bin/env bash
# Assemble the one GitHub Pages artefact (T0.4 S6c, D243): dashboard at the root, mkdocs under docs/.
#
#   BUILD_ID=<git_sha>-<deploy_run_id> assemble_pages_site.sh <dashboard_dir|--placeholder> <mkdocs_site> <out>
#
# env BUILD_ID        required, ^[0-9a-f]{40}-[0-9]+$; written to <out>/build-id.txt (R13 P5.5)
# env PAGES_MAX_BYTES size cap of <out> measured with `du -sb` (default 800000000, N5.1)
set -euo pipefail

fail() {
  echo "assemble_pages_site: $*" >&2
  exit 1
}

if [ "$#" -ne 3 ]; then
  echo "usage: BUILD_ID=<sha>-<run id> $0 <dashboard_dir|--placeholder> <mkdocs_site> <out>" >&2
  exit 2
fi
dashboard=$1
site=$2
out=$3
max_bytes=${PAGES_MAX_BYTES:-800000000}

[[ "${BUILD_ID:-}" =~ ^[0-9a-f]{40}-[0-9]+$ ]] \
  || fail "BUILD_ID must match <40 hex sha>-<run id>, got '${BUILD_ID:-}'"
[[ "$max_bytes" =~ ^[0-9]+$ ]] || fail "PAGES_MAX_BYTES must be an integer, got '$max_bytes'"
[ -f "$site/index.html" ] || fail "mkdocs site '$site' has no index.html (run make docs)"
if [ -e "$out" ] && [ -n "$(ls -A "$out")" ]; then
  fail "output '$out' exists and is not empty"
fi

if [ "$dashboard" != "--placeholder" ]; then
  [ -d "$dashboard" ] || fail "dashboard dir '$dashboard' does not exist"
  [ ! -e "$dashboard/docs" ] || fail "dashboard dir contains docs/ (reserved for the mkdocs site)"
  [ ! -e "$dashboard/build-id.txt" ] || fail "dashboard dir contains build-id.txt"
  link=$(find "$dashboard" -type l -print -quit)
  [ -z "$link" ] || fail "dashboard dir contains a symlink: $link"
fi

mkdir -p "$out"
if [ "$dashboard" = "--placeholder" ]; then
  # <base> makes the relative link work from any 404 path too.
  cat > "$out/index.html" <<'HTML'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<base href="/pruefstand/">
<title>Prüfstand</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>Prüfstand</h1>
<p>The dashboard has no data yet. Read the <a href="docs/">documentation</a>.</p>
</body>
</html>
HTML
  cp "$out/index.html" "$out/404.html"
else
  cp -a "$dashboard/." "$out/"
fi
cp -a "$site" "$out/docs"
: > "$out/.nojekyll"
printf '%s\n' "$BUILD_ID" > "$out/build-id.txt"

size=$(du -sb "$out" | cut -f1)
if [ "$size" -gt "$max_bytes" ]; then
  fail "assembled site is $size bytes, over the limit of $max_bytes bytes"
fi
du -sb "$out"
