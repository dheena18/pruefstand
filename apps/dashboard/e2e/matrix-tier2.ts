// Tier-2 rows (synthetic fixtures of derive_tier2.mjs) of the ui-spec §14.2 matrix: summaries incl. the judge flags,
// the paired-statistics diff, slices with gated and informational sections, and the cases list of a hard-fail run.
import {
  T2_DEGRADED,
  T2_DRIFT,
  T2_FAIL,
  T2_FALLBACK,
  T2_HARD_FAIL,
  T2_PASS,
  T2_UNSUPPORTED,
  T2_WARN,
} from "./fixture-ids";
import { row, run, type Row } from "./matrix";

const summary = (state: string, id: string, expect: Row["expect"]): Row =>
  row({ page: "Run summary", state, set: "populated", fixtureRunId: id, path: run(id), expect });

export const tier2Rows: Row[] = [
  summary("S-PASS (tier 2)", T2_PASS, { words: ["PASS"], absentStates: ["S-TIER1"] }),
  summary("S-WARN", T2_WARN, { words: ["WARN"] }),
  summary("S-FAIL", T2_FAIL, { words: ["FAIL"] }),
  summary("S-HARD-FAIL (tier 2)", T2_HARD_FAIL, { words: ["FAIL"] }),
  summary("S-JUDGE-FALLBACK", T2_FALLBACK, { states: ["S-JUDGE-FALLBACK"] }),
  summary("S-JUDGE-DEGRADED", T2_DEGRADED, { states: ["S-JUDGE-DEGRADED"] }),
  summary("S-JUDGE-DRIFT", T2_DRIFT, { states: ["S-JUDGE-DRIFT"] }),
  summary("S-UNSUPPORTED", T2_UNSUPPORTED, { states: ["S-UNSUPPORTED"] }),
  ...[
    ["S-FAIL", T2_FAIL],
    ["S-WARN", T2_WARN],
    ["S-PASS (tier 2)", T2_PASS],
  ].map(([state, id]) =>
    row({
      page: "Diff",
      state: String(state),
      set: "populated",
      fixtureRunId: String(id),
      path: `${run(String(id))}diff/`,
      expect: { keys: ["subnav.diff"], absentStates: ["S-TIER1"], hydrated: true },
    }),
  ),
  ...[
    ["S-FAIL", T2_FAIL],
    ["S-PASS (tier 2)", T2_PASS],
  ].map(([state, id]) =>
    row({
      page: "Slices",
      state: String(state),
      set: "populated",
      fixtureRunId: String(id),
      path: `${run(String(id))}slices/`,
      expect: { keys: ["subnav.slices"], absentStates: ["S-TIER1"], hydrated: true },
    }),
  ),
  row({
    page: "Cases list",
    state: "S-HARD-FAIL (tier 2)",
    set: "populated",
    fixtureRunId: T2_HARD_FAIL,
    path: `${run(T2_HARD_FAIL)}cases/`,
    expect: { keys: ["cases.title"], hydrated: true },
  }),
];
