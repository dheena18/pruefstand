#!/usr/bin/env bash
# serve_under_base.sh <site> <base> <tmp> [port]: serve a built site the way GitHub Pages serves a project site
# (ui-spec §14.2, UI12-06). Makes <tmp>/<base>/ = the site, copies <site>/404.html to <tmp>/404.html (Pages serves the
# site-root 404 for the whole project path) and serves <tmp> header-free on <port> (default 4177) in the foreground.
# With SERVE_PREPARE_ONLY=1 it only lays out <tmp>.
set -euo pipefail

site="${1:?usage: serve_under_base.sh <site> <base> <tmp> [port]}"
base="${2:?base path, e.g. /pruefstand}"
tmp="${3:?tmp dir}"
port="${4:-4177}"

case "$base" in
  /?*) ;;
  *) echo "serve_under_base: base must look like /name, got " >&2; exit 2 ;;
esac
[ -f "$site/404.html" ] || { echo "serve_under_base: $site/404.html missing (build the set first)" >&2; exit 1; }

here="$(cd "$(dirname "$0")/../.." && pwd)"
rm -rf "$tmp"
mkdir -p "$tmp$base"
cp -a "$site/." "$tmp$base/"
cp "$site/404.html" "$tmp/404.html"
printf {cleanUrls: false, trailingSlash: true}n > "$tmp/serve.json"

if [ "${SERVE_PREPARE_ONLY:-0}" = "1" ]; then
  echo "serve_under_base: prepared $tmp"
  exit 0
fi
exec node "$here/apps/dashboard/e2e/static-server.mjs" "$tmp" "$port"
