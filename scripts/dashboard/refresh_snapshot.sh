#!/usr/bin/env bash
# refresh_snapshot.sh <live-e2e run id>...: the whole ui-spec §14.1 pipeline in one command.
#   1. download the real tier-1 artefacts of the given GitHub Actions runs into fixtures/raw/<run_id>/
#      (live-baseline -> F-BASE, live-run -> F-T1, e2e-baseline -> F-E2E-BASE,
#       scenario-run-tenant_filter_post_topk -> F-HARD-FAIL) and write roles.json
#   2. re-gate F-T1 against F-BASE (pruefstand gate) so the pair is coherent
#   3. derive.py                 F-PARTIAL, F-NO-BASELINE, F-JUDGE-SKIPPED
#   4. pruefstand export-dashboard --runs fixtures/raw --out fixtures/populated
#   5. derive_fixtures.mjs       D-BASELINE-MISSING, D-MANY, fixtures/empty, manifests, SOURCE.md
# Needs `gh` (env -u GITHUB_TOKEN -u GH_TOKEN gh ... if a token variable is exported), jq, uv, node.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: refresh_snapshot.sh <run id>..." >&2; exit 2; }
root="$(cd "$(dirname "$0")/../.." && pwd)"
fixtures="$root/apps/dashboard/fixtures"
raw="$fixtures/raw"
repo="dheena18/pruefstand"
gh_() { env -u GITHUB_TOKEN -u GH_TOKEN gh "$@"; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$raw"
roles="{}"
sources="{}"

adopt() {  # adopt <role> <run id> <artifact> <directory holding run.json>
  local role="$1" gh_run="$2" artifact="$3" dir="$4" run_id
  run_id="$(jq -r .run_id "$dir/run.json")"
  rm -rf "${raw:?}/$run_id"
  cp -r "$dir" "$raw/$run_id"
  roles="$(jq --arg r "$role" --arg i "$run_id" '. + {($r): $i}' <<<"$roles")"
  sources="$(jq --arg r "$role" --arg g "$gh_run" --arg a "$artifact" '. + {($r): {github_run: $g, artifact: $a}}' <<<"$sources")"
  echo "adopted $role = $run_id ($artifact of run $gh_run)"
}

for gh_run in "$@"; do
  names="$(gh_ api "repos/$repo/actions/runs/$gh_run/artifacts" --jq '.artifacts[] | select(.expired | not) | .name')"
  for artifact in live-baseline live-run e2e-baseline scenario-run-tenant_filter_post_topk; do
    grep -qx "$artifact" <<<"$names" || continue
    gh_ run download "$gh_run" -R "$repo" -n "$artifact" -D "$tmp/$gh_run-$artifact"
    base="$tmp/$gh_run-$artifact"
    case "$artifact" in
      live-baseline) rm -f "$base/gate.json"; adopt F-BASE "$gh_run" "$artifact" "$base" ;;  # not gated: S-NOT-GATED
      live-run) rm -f "$base/evidence.json" "$base/report.html"; adopt F-T1 "$gh_run" "$artifact" "$base" ;;
      e2e-baseline) adopt F-E2E-BASE "$gh_run" "$artifact" "$(dirname "$(ls "$base"/*/run.json | head -n 1)")" ;;
      scenario-run-*) adopt F-HARD-FAIL "$gh_run" "$artifact" "$(dirname "$(ls "$base"/*/run.json | head -n 1)")" ;;
    esac
  done
done
for need in F-BASE F-T1 F-HARD-FAIL; do
  jq -e --arg n "$need" 'has($n)' <<<"$roles" >/dev/null || { echo "no artefact for $need in the given runs" >&2; exit 1; }
done

cp "$root/examples/live/pruefstand.yaml" "$raw/pruefstand.yaml"
jq -n --argjson roles "$roles" --argjson sources "$sources" \
  '{config: "pruefstand.yaml", roles: $roles, sources: $sources}' > "$raw/roles.json"

t1="$(jq -r '.roles["F-T1"]' "$raw/roles.json")"
base="$(jq -r '.roles["F-BASE"]' "$raw/roles.json")"
cd "$root"
uv run pruefstand gate --config "$raw/pruefstand.yaml" --candidate "$raw/$t1" --baseline "$raw/$base" || true
uv run python scripts/dashboard/derive.py
rm -rf "$fixtures/populated" "$fixtures/empty"
uv run pruefstand export-dashboard --runs "$raw" --out "$fixtures/populated"
node scripts/dashboard/derive_fixtures.mjs
node scripts/dashboard/check_fixture_states.mjs
