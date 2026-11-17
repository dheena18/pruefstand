#!/usr/bin/env bash
# scripts/deploy/build_dashboard.sh <data-dir>: build the dashboard of the verified dashboard-data tree (T8.5 S2).
# `deploy.yml` job `build-dashboard` calls it after `verify_dashboard_export.py`; the tree is used as is (no pruning,
# no filtering, UI13-20). Builds with NEXT_BASE_PATH=/pruefstand and NEXT_PUBLIC_DEMO_API_URL (empty = no Try-it
# link, UI12-19), i.e. `pnpm build`: validate_data.mjs, next build, csp.mjs, check_csp.mjs. Then writes
# out/BUILD.json {data_sha, deploy_run_id, git_sha} and prints `du -sb out`.
# env: DATA_SHA (required), DEPLOY_RUN_ID (required), GIT_SHA (default: git rev-parse HEAD),
#      NEXT_PUBLIC_DEMO_API_URL (default empty), DASHBOARD_APP_DIR (default apps/dashboard; tests)
set -euo pipefail

data_dir="${1:?usage: build_dashboard.sh <data-dir>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
app="${DASHBOARD_APP_DIR:-$root/apps/dashboard}"
data_sha="${DATA_SHA:?DATA_SHA is required}"
run_id="${DEPLOY_RUN_ID:?DEPLOY_RUN_ID is required}"
git_sha="${GIT_SHA:-$(git -C "$root" rev-parse HEAD)}"

case "$data_sha" in *[!0-9a-f]* | "") echo "build_dashboard: DATA_SHA must be a hex commit SHA" >&2; exit 2 ;; esac
case "$run_id" in *[!0-9]* | "") echo "build_dashboard: DEPLOY_RUN_ID must be a number" >&2; exit 2 ;; esac
[ -f "$data_dir/manifest.json" ] || { echo "build_dashboard: $data_dir has no manifest.json (not a dashboard-data tree)" >&2; exit 2; }
data_dir="$(cd "$data_dir" && pwd)"

rm -rf "$app/out"
(
  cd "$app"
  DASHBOARD_DATA_DIR="$data_dir" NEXT_BASE_PATH=/pruefstand NEXT_PUBLIC_DEMO_API_URL="${NEXT_PUBLIC_DEMO_API_URL:-}" pnpm build
)
[ -f "$app/out/index.html" ] || { echo "build_dashboard: the build produced no out/index.html" >&2; exit 1; }

printf '{"data_sha": "%s", "deploy_run_id": %s, "git_sha": "%s"}\n' "$data_sha" "$run_id" "$git_sha" > "$app/out/BUILD.json"
du -sb "$app/out"
