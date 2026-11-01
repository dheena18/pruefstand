# T2.1: data downloads (pins in data/sources.yaml, raw files in data/raw/, git-ignored).
.PHONY: data data-verify no-raw-data

data:
	uv run python data/download.py

data-verify:
	uv run python data/download.py --verify-only

no-raw-data:
	uv run python scripts/check_no_raw_data.py

# CI guard against committed corpora rides on the existing file-size target (S7).
file-size: no-raw-data
