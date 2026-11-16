// Fixture states of ui-spec §14.1, computed from a data tree (shared by check_fixture_states.mjs and SOURCE.md).
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { MAX_CASE_RUNS } from "./limits.mjs";

const readJson = (file) => JSON.parse(readFileSync(file, "utf8"));

/** The T8.1 rows of the state table: id -> predicate over (entry, ctx). `ctx` knows the tree. */
export const T81_STATES = {
  "S-NOT-GATED": (e) => e.status === null && e.complete,
  "S-TIER1": (e) => e.stack === "live" && e.status !== null,
  "S-PASS": (e) => e.stack === "live" && e.status === "pass",
  "S-HARD-FAIL": (e, c) => e.stack === "live" && e.status === "fail" && c.gate(e)?.hard_fails.length > 0,
  "S-PARTIAL": (e) => !e.complete && e.status === null,
  "S-JUDGE-SKIPPED": (e) => e.judge_mode === "skipped" && e.status !== null,
  "S-NO-BASELINE": (e) => e.no_baseline && e.baseline_run_id === null,
  "S-BASELINE-MISSING": (e, c) => e.baseline_run_id !== null && !c.ids.has(e.baseline_run_id),
  "S-CASES-PRUNED": (e, c) => !c.published.has(e.run_id),
};

/** The tier-2 rows (T8.3): synthetic runs from `derive_tier2.mjs`, `stack` is `a40`. */
export const T83_STATES = {
  "S-PASS (tier 2)": (e) => e.stack === "a40" && e.status === "pass" && !e.judge_fallback && !e.judge_degraded && !e.judge_drift,
  "S-WARN": (e) => e.stack === "a40" && e.status === "warn",
  "S-FAIL": (e, c) => e.stack === "a40" && e.status === "fail" && c.gate(e)?.hard_fails.length === 0,
  "S-INSUFFICIENT": (e, c) => e.stack === "a40" && c.gate(e)?.decisions.some((d) => d.status === "insufficient_data") === true,
  "S-HARD-FAIL (tier 2)": (e, c) => e.stack === "a40" && e.status === "fail" && c.gate(e)?.hard_fails.length > 0,
  "S-JUDGE-FALLBACK": (e) => e.stack === "a40" && e.judge_fallback === true,
  "S-JUDGE-DEGRADED": (e) => e.stack === "a40" && e.judge_degraded === true,
  "S-JUDGE-DRIFT": (e) => e.stack === "a40" && e.judge_drift === true,
  "S-UNSUPPORTED": (e) => e.stack === "a40" && e.status === "unsupported_config",
};

export function context(dir) {
  const index = readJson(path.join(dir, "runs/index.json"));
  const ordered = [...index.runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.run_id < b.run_id ? -1 : 1));
  return {
    index,
    ids: new Set(index.runs.map((r) => r.run_id)),
    published: new Set(ordered.slice(0, MAX_CASE_RUNS).map((r) => r.run_id)),
    gate: (e) => (e.status === null ? null : readJson(path.join(dir, "runs", e.run_id, "gate.json"))),
  };
}

/** state id -> run ids that show it. */
export function statesOf(dir) {
  const ctx = context(dir);
  const found = {};
  for (const [state, test] of Object.entries({ ...T81_STATES, ...T83_STATES })) {
    found[state] = ctx.index.runs.filter((e) => test(e, ctx)).map((e) => e.run_id);
  }
  found["L-POPULATED"] = ctx.index.runs.length > 0 ? ["runs/index.json"] : [];
  return found;
}

/** Real cases the matrix needs: refused, error and `en` (any published shard). */
export function caseFacts(dir) {
  const facts = { refused: [], error: [], en: [] };
  const casesDir = path.join(dir, "cases");
  if (!existsSync(casesDir)) return facts;
  for (const run of readdirSync(casesDir).sort()) {
    for (const name of readdirSync(path.join(casesDir, run)).sort()) {
      for (const c of readJson(path.join(casesDir, run, name)).cases) {
        const ref = `${run}/${c.case_id}`;
        if (c.refused === true) facts.refused.push(ref);
        if (c.error !== null) facts.error.push(ref);
        if (c.lang === "en") facts.en.push(ref);
      }
    }
  }
  return facts;
}
