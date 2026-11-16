# CI repo hygiene (T0.2): the workflow guard also runs as part of `make lint`.
.PHONY: workflows
workflows:
	uv run python scripts/check_workflows.py .github/workflows --actions .github/actions

lint: workflows
