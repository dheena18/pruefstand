# Model shortlist benchmark (T3.1b). Runs UNDER the single VM GPU lock (pruefstand-lock, D212) against the models
# already resident (day set); it never pulls, removes or swaps a model (swaps are the lead's, ADR-0019 swap rule).
# BENCH_PHASES: comma list of quality,throughput,parallel,json,vram,kv,longctx. Output: experiments/model_selection/results/.
.PHONY: bench-models

BENCH_PHASES ?= quality,throughput,parallel,json,vram,kv,longctx

bench-models:
	PYTHONPATH=experiments pruefstand-lock uv run python -m model_selection.bench --phases $(BENCH_PHASES)
