// Run ids of the fixture roles the specs need, resolved from the committed `fixtures/populated/runs/index.json` by
// their exported shape (data files only: the specs never recompute a metric). A refreshed snapshot keeps working.
import { readFileSync } from "node:fs";
import path from "node:path";

interface IndexEntry {
  run_id: string;
  status: string | null;
  stack: string;
  n_cases: number;
  created_at: string;
  complete: boolean;
  no_baseline: boolean;
  baseline_run_id: string | null;
}

const MAX_CASE_RUNS = 20;
const root = path.join(import.meta.dirname, "..", "fixtures", "populated");
const runs = (
  JSON.parse(readFileSync(path.join(root, "runs", "index.json"), "utf8")) as { runs: IndexEntry[] }
).runs;
const ids = new Set(runs.map((r) => r.run_id));
const newest = [...runs].sort(
  (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.run_id < b.run_id ? -1 : 1),
);
const published = new Set(newest.slice(0, MAX_CASE_RUNS).map((r) => r.run_id));

function pick(role: string, predicate: (r: IndexEntry) => boolean): string {
  const found = newest.find((r) => published.has(r.run_id) && predicate(r));
  if (!found)
    throw new Error(`fixture role ${role} not found in fixtures/populated/runs/index.json`);
  return found.run_id;
}

/** The 1,500-case run in 3 shards (D-MANY). */
export const MANY_RUN = pick("D-MANY", (r) => r.n_cases >= 1500);
/** F-HARD-FAIL: a real tier-1 run with status `fail` (hard fails), not D-MANY. */
export const FAIL_RUN = pick("F-HARD-FAIL", (r) => r.status === "fail" && r.run_id !== MANY_RUN);
/** First failing case of F-HARD-FAIL (a static case page exists for it). */
export const FAIL_CASE = (
  JSON.parse(readFileSync(path.join(root, "cases", FAIL_RUN, "0.json"), "utf8")) as {
    cases: { case_id: string; failing: boolean }[];
  }
).cases.find((c) => c.failing)?.case_id as string;
/** F-T1: a gated tier-1 PASS with a baseline in the index. */
export const PASS_RUN = pick(
  "F-T1",
  (r) => r.status === "pass" && r.baseline_run_id !== null && ids.has(r.baseline_run_id),
);
export const PARTIAL_RUN = pick("F-PARTIAL", (r) => !r.complete);
export const NO_BASELINE_RUN = pick("F-NO-BASELINE", (r) => r.no_baseline);
export const NOT_GATED_RUN = pick("F-BASE", (r) => r.status === null && r.complete);
export const BASELINE_MISSING_RUN = pick(
  "D-BASELINE-MISSING",
  (r) => r.baseline_run_id !== null && !ids.has(r.baseline_run_id),
);
/** S-CASES-PRUNED: the oldest run, outside the newest 20. */
export const PRUNED_RUN = (
  newest.filter((r) => !published.has(r.run_id)).at(-1) ?? fail("S-CASES-PRUNED")
).run_id;

function fail(role: string): never {
  throw new Error(`fixture role ${role} not found`);
}
