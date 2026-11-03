# Model shortlist benchmark (T3.1b). Runs UNDER the single VM GPU lock (pruefstand-lock, D212); it never
# pulls, removes or swaps a model (swaps are the lead's, ADR-0019 swap rule).
#   make bench-models                       day set: the models already resident (BENCH_PHASES: comma list of
#                                           quality,throughput,parallel,json,vram,overhead,kv,longctx)
#   make bench-models CANDIDATE=<tag>       candidate pass for ONE pulled catalogue model (infra/gpu/models.yaml):
#                                           first-load time, German smoke, judge-JSON validity, tok/s at concurrency
#                                           1/4, VRAM from the wrapper status, provisional overhead_gib;
#                                           CANDIDATE_PHASES: comma list of quality,json,throughput
# Output (both): experiments/model_selection/results/<date>.csv, appended, column run_id.
.PHONY: bench-models

BENCH_PHASES ?= quality,throughput,parallel,json,vram,overhead,kv,longctx
CANDIDATE_PHASES ?= quality,json,throughput

bench-models:
ifeq ($(strip $(CANDIDATE)),)
	PYTHONPATH=experiments pruefstand-lock uv run python -m model_selection.bench --phases $(BENCH_PHASES)
else
	PYTHONPATH=experiments pruefstand-lock uv run python -m model_selection.bench_candidate --candidate "$(CANDIDATE)" --phases $(CANDIDATE_PHASES)
endif
