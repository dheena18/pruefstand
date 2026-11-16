# D1230: repo lint for `pgrep -f` / `pkill -f` that can match their own or another command line.
.PHONY: self-matching-pgrep

self-matching-pgrep:
	uv run python scripts/check_self_matching_pgrep.py

# Rides on the existing file-size target, which CI runs (same pattern as no-raw-data in mk/data.mk).
file-size: self-matching-pgrep
