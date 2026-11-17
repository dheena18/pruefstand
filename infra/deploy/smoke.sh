#!/usr/bin/env bash
# infra/deploy/smoke.sh <base-url>: smoke test of a running public demo (T8.5 S5; demo-deploy and demo-ready).
# 1. GET /v1/health answers {"status": "ok"}; 2. one canned German query for a fixed tenant answers 200 with at
# least one citation; 3. a public-mode error (unknown tenant) answers a non-2xx JSON body whose `code` is
# invalid_request (the fixed error body of interfaces §16). Exit 0 all ok, 1 a check failed, 2 usage.
# env: SMOKE_TENANT (kanzlei_mueller), SMOKE_QUESTION (canned), SMOKE_QUERY_TIMEOUT_S (180)
set -euo pipefail

base="${1:?usage: smoke.sh <base-url>}"
base="${base%/}"
tenant="${SMOKE_TENANT:-kanzlei_mueller}"
question="${SMOKE_QUESTION:-Welche Kündigungsfrist gilt nach zwei Jahren?}"
timeout_s="${SMOKE_QUERY_TIMEOUT_S:-180}"
command -v jq >/dev/null || { echo "smoke: jq is required" >&2; exit 2; }
case "$base" in http://* | https://*) ;; *) echo "smoke: base URL must start with http:// or https://" >&2; exit 2 ;; esac

fail() { echo "smoke: FAIL $*" >&2; exit 1; }
post() { # <json body>: prints "<http status>\n<body>"
  curl -sS --retry 3 --retry-all-errors --retry-delay 5 --max-time "$timeout_s" -o - -w '\n%{http_code}' \
    -X POST -H 'content-type: application/json' --data "$1" "$base/v1/query"
}

health="$(curl -sS --retry 3 --retry-all-errors --retry-delay 5 --max-time 30 "$base/v1/health")" || fail "health: no answer"
jq -e '.status == "ok"' <<<"$health" >/dev/null || fail "health: status is not ok: $health"
echo "smoke: health ok"

reply="$(post "$(jq -cn --arg t "$tenant" --arg q "$question" '{tenant_id: $t, question: $q}')")" || fail "query: no answer"
code="${reply##*$'\n'}"
body="${reply%$'\n'*}"
[ "$code" = "200" ] || fail "query: HTTP $code: $body"
jq -e '(.citations | length) >= 1' <<<"$body" >/dev/null || fail "query: no citation in the answer"
echo "smoke: query answered with $(jq '.citations | length' <<<"$body") citation(s)"

reply="$(post '{"tenant_id": "no_such_tenant", "question": "x"}')" || fail "error probe: no answer"
code="${reply##*$'\n'}"
body="${reply%$'\n'*}"
case "$code" in 4?? | 5??) ;; *) fail "error probe: HTTP $code, expected an error" ;; esac
jq -e '.code == "invalid_request"' <<<"$body" >/dev/null || fail "error probe: body has no code invalid_request: $body"
echo "smoke: error body ok ($code)"
echo "smoke: all checks passed"
