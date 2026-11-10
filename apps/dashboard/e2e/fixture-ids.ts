// Run ids of the fixture roles the specs need, read from the committed `fixtures/populated/runs/index.json`
// (data files only: the spec never recomputes a metric, it picks rows by their exported status/shape).
import { readFileSync } from "node:fs";
import path from "node:path";

interface IndexEntry {
  run_id: string;
  status: string | null;
  stack: string;
  n_cases: number;
  created_at: string;
}

const root = path.join(import.meta.dirname, "..", "fixtures", "populated");
const runs = (
  JSON.parse(readFileSync(path.join(root, "runs", "index.json"), "utf8")) as { runs: IndexEntry[] }
).runs;

/** The 1,500-case run in 3 shards (D-MANY). */
export const MANY_RUN = (runs.find((r) => r.n_cases >= 1500) ?? fail("D-MANY")).run_id;
/** A published run with status `fail` that is not D-MANY (F-HARD-FAIL, real tier-1 hard fail). */
export const FAIL_RUN = (
  runs.find((r) => r.status === "fail" && r.run_id !== MANY_RUN) ?? fail("F-FAIL")
).run_id;

function fail(role: string): never {
  throw new Error(`fixture role ${role} not found in fixtures/populated/runs/index.json`);
}
