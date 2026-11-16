// Tier-2 fixtures of ui-spec §14.1 (T8.3): F-PASS, F-WARN, F-FAIL, D-T2-HARD-FAIL and the four D-JUDGE-FLAGS runs.
// The real tier-2 runs live in the private-by-token repo `pruefstand-dashboard-data`, which the VM cannot read, so
// these are SYNTHETIC: each is a clone of a real tier-1 export (F-T1, or F-HARD-FAIL for the hard-fail run) whose
// `stack` is `a40` and whose gate.json / slices.json carry paired-bootstrap decisions with fixed, hand-chosen numbers
// (no randomness). Status, counts and flags are consistent with each other; the numbers are not measurements. SOURCE.md
// says so. Deterministic: same input, same bytes.
import { derivedRunId, cloneRun } from "./derive_fixtures.mjs";

const TENANTS = ["kanzlei_mueller", "stadtwerke_sued"];
/** metric, dimension, value, baseline mean, delta (candidate - baseline), clusters */
const GATED = [
  ["context_recall", "overall", "overall", 0.82, 0.01, 60],
  ["ndcg_at_k", "overall", "overall", 0.71, 0.0, 60],
  ["citation_recall", "overall", "overall", 0.64, -0.01, 60],
  ["language_match", "lang", "de", 0.97, 0.0, 44],
  ["language_match", "lang", "en", 0.95, 0.0, 16],
  ["context_recall", "tenant", TENANTS[0], 0.8, 0.01, 31],
  ["context_recall", "tenant", TENANTS[1], 0.84, 0.0, 29],
];

function decision([metric, dimension, value, base, delta, clusters], status, over = {}) {
  const se = 0.02;
  const insufficient = status === "insufficient_data";
  return {
    baseline_mean: base,
    candidate_mean: Math.round((base + delta) * 1000) / 1000,
    dimension,
    gated: true,
    informational_reason: null,
    max_drop: 0.05,
    max_value: null,
    mde: insufficient ? null : 0.06,
    metric,
    n_clusters: clusters,
    notable: false,
    p_adjusted: insufficient ? null : status === "fail" ? 0.004 : status === "warn" ? 0.04 : 0.62,
    result: insufficient
      ? null
      : {
          ci_high: Math.round((delta + 1.96 * se) * 1000) / 1000,
          ci_low: Math.round((delta - 1.96 * se) * 1000) / 1000,
          confidence: 0.95,
          mean_diff: delta,
          method: "bootstrap",
          n_cases: clusters + 8,
          n_clusters: clusters,
          n_resamples: 10000,
          p_value: status === "fail" ? 0.001 : status === "warn" ? 0.02 : 0.31,
          se,
        },
    status,
    value,
    ...over,
  };
}

function sliceRow(d) {
  return {
    baseline_mean: d.baseline_mean,
    candidate_mean: d.candidate_mean,
    ci_high: d.result?.ci_high ?? null,
    ci_low: d.result?.ci_low ?? null,
    dimension: d.dimension,
    gated: d.gated,
    informational_reason: d.informational_reason,
    kind: "decision",
    max_drop: d.max_drop,
    max_value: d.max_value,
    mde: d.mde,
    mean_diff: d.result?.mean_diff ?? null,
    metric: d.metric,
    n_clusters: d.n_clusters,
    notable: d.notable,
    status: d.status,
    value: d.value,
  };
}

/** The paired decisions of one profile: `pass`, `warn` (one WARN row), `fail` (one FAIL, one INSUFFICIENT row). */
function decisionsFor(profile) {
  return GATED.map((g, i) => {
    if (profile === "warn" && i === 1) return decision([g[0], g[1], g[2], g[3], -0.04, g[5]], "warn");
    if (profile === "fail" && i === 0) return decision([g[0], g[1], g[2], g[3], -0.12, g[5]], "fail");
    if (profile === "fail" && i === 4) return decision(g, "insufficient_data", { n_clusters: 6 });
    return decision(g, "pass");
  });
}

const RUN_STATUS = { pass: "pass", warn: "warn", fail: "fail", unsupported: "unsupported_config" };

/** Turns a cloned tier-1 export into a tier-2 one (in place on run, gate, slices and the index entry). */
function toTier2({ run, gate, slices, entry }, profile, flags = {}) {
  const decisions = decisionsFor(profile === "unsupported" ? "pass" : profile);
  const status = RUN_STATUS[profile];
  Object.assign(run, { stack: "a40", judge_mode: "local", judged_cases: run.n_cases, workload: "pr" }, flags);
  Object.assign(entry, { stack: "a40", judge_mode: "local", status, workload: "pr" }, flags);
  gate.status = status;
  gate.decisions = decisions;
  gate.notable_slices = [];
  gate.likely_cause = profile === "fail" ? "retrieval" : null;
  slices.rows = [...slices.rows.filter((r) => r.kind === "absolute"), ...decisions.map(sliceRow)];
}

/**
 * Appends the eight tier-2 runs to the exported tree. `anchor` is the date of the newest non-tier-2 run; the new runs
 * are dated just below it so they are case-published (newest 20) and the 1,500-case run stays the newest.
 */
export function deriveTier2(populated, t1, hard, entries, anchorMs) {
  const specs = [
    ["F-PASS", t1, "pass", {}],
    ["F-WARN", t1, "warn", {}],
    ["F-FAIL", t1, "fail", {}],
    ["D-T2-HARD-FAIL", hard, "fail", {}],
    ["D-JUDGE-FALLBACK", t1, "pass", { judge_fallback: true }],
    ["D-JUDGE-DEGRADED", t1, "pass", { judge_degraded: true }],
    ["D-JUDGE-DRIFT", t1, "pass", { judge_drift: true }],
    ["D-UNSUPPORTED", t1, "unsupported", {}],
  ];
  const ids = {};
  specs.forEach(([name, source, profile, flags], i) => {
    const date = new Date(anchorMs - (i + 1) * 5_000);
    const id = derivedRunId(name, date);
    const done = cloneRun(populated, source, id, date, {
      withCases: true,
      edit: (parts) => toTier2(parts, profile, flags),
    });
    entries.push(done.entry);
    ids[name] = id;
  });
  return ids;
}
