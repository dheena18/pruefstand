# T1.11: the live e2e gate tests under one stack session (stack.lock from up to down, A13-M8).
.PHONY: e2e-live

# Brings the `live` stack up, indexes the slice, runs the five scenarios of packages/pruefstand/tests/e2e.
# Needs the pinned models (uv run python scripts/models/fetch.py --manifest infra/models/live-models.yaml).
# One scenario: make e2e-live SCENARIO=tenant_filter_post_topk
SCENARIO ?=
e2e-live:
	$(MAKE) --no-print-directory stack-run PROFILES="core live dev" \
	    CMD="make --no-print-directory index-slice && PRUEFSTAND_E2E_SCENARIO=$(SCENARIO) uv run pytest -m \"e2e and live\" packages/pruefstand/tests/e2e -v"
