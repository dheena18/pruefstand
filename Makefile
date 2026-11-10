# Prüfstand: the single definition of the Make targets is CLAUDE.md §3.
# Later tasks add their own targets in mk/<area>.mk (included at the bottom); never edit this file for that.
SHELL := /bin/bash
.DEFAULT_GOAL := check
.PHONY: install lint format typecheck arch file-size test test-slow test-e2e test-integration \
        test-live test-gpu cassettes coverage schemas schemas-fresh docs ui-check experiments check clean

# One root list for pytest `pythonpath` and mypy `mypy_path` (R9 X4.2); same order as CLAUDE.md §3.
IMPORT_ROOTS := packages/pruefstand/src apps/rag-demo/src packages/pruefstand/tests apps/rag-demo/tests \
    scripts data experiments tools action infra/gpu benchmarks infra/vm infra/cluster \
    infra/gate-executor/orchestrator infra/gate-executor/llm-proxy
EXISTING_ROOTS := $(foreach r,$(IMPORT_ROOTS),$(wildcard $(r)))

export LITELLM_LOCAL_MODEL_COST_MAP := True
PYTEST := uv run pytest
UNIT_MARKERS := not integration and not e2e and not live and not gpu and not slow and not network

# Run pytest; exit code 5 ("no tests collected") counts as success.
define run_pytest
$(PYTEST) $(1); rc=$$?; if [ $$rc -ne 0 ] && [ $$rc -ne 5 ]; then exit $$rc; fi
endef

install:
	uv sync --all-packages --all-extras
	@if [ -f apps/dashboard/package.json ]; then if command -v pnpm >/dev/null; then (cd apps/dashboard && pnpm install); else echo "install: pnpm not installed, dashboard dependencies skipped"; fi; fi

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

# mypy --strict once per existing import root (R12 N6.3, D266): one run over several trees would
# fail with duplicate module names (every root with tests/ maps it to `tests`).
typecheck:
	@$(foreach r,$(EXISTING_ROOTS),echo ">> mypy $(r)"; uv run mypy $(r) || exit 1;) true

arch:
	uv run lint-imports

file-size:
	uv run python scripts/check_code_limits.py
	uv run python scripts/check_test_locations.py

test:
	@$(call run_pytest,-m "$(UNIT_MARKERS)")
	@$(call run_pytest,--doctest-modules packages/pruefstand/src -q)

test-slow:
	@$(call run_pytest,-m slow -n auto)

test-e2e:
	@$(call run_pytest,-m e2e)

test-integration:
	@$(call run_pytest,-m integration)

test-live:
	@$(call run_pytest,-m live)

test-gpu:
	@$(call run_pytest,-m gpu)

cassettes:
	@if [ -f scripts/models/record_cassettes.sh ]; then bash scripts/models/record_cassettes.sh; \
	else echo "available after T1.4"; fi

coverage:
	@rm -f .coverage coverage.json
	@$(call run_pytest,--cov -m "$(UNIT_MARKERS)")
	@$(call run_pytest,--doctest-modules packages/pruefstand/src -q --cov --cov-append --cov-report=json --cov-report=term)
	uv run python scripts/check_coverage.py

schemas:
	@if uv run pruefstand schema --help >/dev/null 2>&1; then uv run pruefstand schema export --out schemas/; \
	else echo "available after T1.10"; fi

schemas-fresh:
	$(MAKE) schemas && git diff --exit-code -- schemas/ && test -z "$$(git status --porcelain -- schemas/)"

docs:
	@if [ -f mkdocs.yml ]; then uv run mkdocs build --strict; else echo "docs: mkdocs.yml not there yet (T0.4), skipped"; fi

ui-check:
	@if [ -f apps/dashboard/package.json ]; then set -e; \
	  (cd apps/dashboard && pnpm lint); (cd apps/dashboard && pnpm typecheck); \
	  scripts/dashboard/build_set.sh populated; scripts/dashboard/build_set.sh empty; \
	  node scripts/dashboard/check_fixture_states.mjs; \
	  (cd apps/dashboard && DASHBOARD_SETS_PREBUILT=1 pnpm test:coverage); \
	  (cd apps/dashboard && pnpm exec playwright test); \
	  $(MAKE) ui-basepath; \
	else echo "ui-check: apps/dashboard not there yet (T8.1), skipped"; fi

experiments:
	@if [ -f experiments/run_all.py ]; then uv run python experiments/run_all.py; \
	else echo "experiments: experiments/run_all.py not there yet (T7.4), skipped"; fi

check: lint typecheck arch file-size coverage

clean:
	rm -rf .coverage coverage.json htmlcov .pytest_cache .mypy_cache .ruff_cache build dist site
	find . -path ./.venv -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +

-include mk/*.mk
