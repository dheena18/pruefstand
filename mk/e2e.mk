# T1.11: the live e2e gate tests under one stack session (stack.lock from up to down, A13-M8).
.PHONY: e2e-live

E2E_SCENARIOS := good tenant_filter_post_topk shared_public_unfiltered system_prompt_guard_off injection_guard_off
# Overall limit of the suite in seconds (stack up and down are outside it; five scenarios take about 25 minutes).
E2E_TIMEOUT ?= 3600
SCENARIO ?=

# Brings the `live` stack up, indexes the slice, runs the five scenarios of packages/pruefstand/tests/e2e.
# Needs the pinned models (uv run python scripts/models/fetch.py --manifest infra/models/live-models.yaml).
# One scenario: make e2e-live SCENARIO=tenant_filter_post_topk. The value is checked against the known names
# before anything starts, so it never reaches a shell unchecked.
e2e-live:
	@$(if $(or $(word 2,$(SCENARIO)),$(filter-out $(E2E_SCENARIOS),$(SCENARIO))),$(error SCENARIO must be empty or one of: $(E2E_SCENARIOS)),:)
	$(MAKE) --no-print-directory stack-run PROFILES="core live dev" \
	    CMD="make --no-print-directory index-slice && PRUEFSTAND_E2E_SCENARIO=$(SCENARIO) timeout $(E2E_TIMEOUT) uv run pytest -m \"e2e and live\" packages/pruefstand/tests/e2e -v"
