import path from "node:path";

import { loadLabels, loadRunIndex } from "@/lib/data";
import { loadRunContext, type RunContext } from "@/lib/run-context";
import type { GateReport, LabelsDocument, RunIndexEntry, SliceDecision } from "@/lib/types";

export const POPULATED = path.join(__dirname, "../fixtures/populated");
export const EMPTY = path.join(__dirname, "../fixtures/empty");

/** Real fixture runs (fixtures/populated/SOURCE.md). */
export const IDS = {
  tier1: "20261103T123537-e01927",
  hardFail: "20261103T124130-8ee0ce",
  partial: "20261103T123637-fa58d9",
  noBaseline: "20261103T123737-95d79b",
  judgeSkipped: "20261103T123837-5d3b0f",
  baselineMissing: "20261103T124230-46de12",
  notGated: "20261103T112731-e15f0e",
  pruned: "20261102T002731-2558d7",
} as const;

export const ctxOf = (id: string): Promise<RunContext> => loadRunContext(id, POPULATED);
export const labelsOf = (): Promise<LabelsDocument> => loadLabels(POPULATED);
export const indexOf = async (): Promise<RunIndexEntry[]> => (await loadRunIndex(POPULATED)).runs;

export function decision(over: Partial<SliceDecision> = {}): SliceDecision {
  return {
    metric: "context_recall",
    dimension: "overall",
    value: "overall",
    status: "pass",
    gated: true,
    baseline_mean: 0.86,
    candidate_mean: 0.77,
    result: {
      mean_diff: -0.09,
      ci_low: -0.12,
      ci_high: -0.06,
      confidence: 0.95,
      method: "bootstrap",
      n_cases: 100,
      n_clusters: 40,
      n_resamples: 1000,
      p_value: 0.01,
      se: 0.02,
    },
    p_adjusted: 0.01,
    mde: 0.06,
    max_drop: 0.05,
    n_clusters: 40,
    ...over,
  };
}

export function gateWith(over: Partial<GateReport>): GateReport {
  return {
    schema_version: "1",
    status: "pass",
    candidate_run_id: "r",
    baseline_run_id: "b",
    eval_fingerprint: "fp",
    decisions: [],
    absolute_checks: [],
    notable_slices: [],
    hard_fails: [],
    top_failing_cases: [],
    likely_cause: null,
    ...over,
  };
}
