import { describe, expect, it } from "vitest";

import {
  applyDiff,
  buildDiffModel,
  ciDomain,
  countRows,
  parseDiffQuery,
  toDiffQuery,
} from "@/lib/diff";
import {
  MAX_BARS,
  chartRows,
  groupOf,
  parseSlicesQuery,
  sectionsFor,
  toSlicesQuery,
} from "@/lib/slices";

import {
  IDS,
  ctxOf,
  decision,
  gateWith,
  indexOf,
  loadSlicesOf,
  sliceRow,
  RESULT,
} from "../fixtures";

describe("diff model", () => {
  it("keeps only block-G rows: informational, notable and absolute rows are not on the page", async () => {
    const ctx = await ctxOf(IDS.tier1);
    const gate = gateWith({
      decisions: [decision(), decision({ gated: false, informational_reason: "judge_drift" })],
      absolute_checks: [decision({ metric: "error_rate", max_value: 0.02 })],
      notable_slices: [decision({ gated: false, notable: true })],
    });
    const model = buildDiffModel({ ...ctx, run: { ...ctx.run, stack: "a40" }, gate });
    expect(model.rows).toHaveLength(1);
    expect(model.tier1).toBeNull();
  });
  it("tier 1: no chart rows, block R rows and the notice data", async () => {
    const ctx = await ctxOf(IDS.tier1);
    const model = buildDiffModel(ctx);
    expect(model.rows).toEqual([]);
    expect(model.tier1).toEqual({ splits: ctx.run.splits, n: ctx.run.n_cases });
    expect(model.reported.length).toBeGreaterThan(0);
    expect(model.reported.every((d) => d.informational_reason != null)).toBe(true);
  });
  it("sorts by status, then Δ ascending, then metric, then slice; null results last", () => {
    const rows = [
      decision({ metric: "b", status: "pass" }),
      decision({ metric: "a", status: "fail", result: { ...RESULT, mean_diff: -0.01 } }),
      decision({ metric: "c", status: "fail", result: { ...RESULT, mean_diff: -0.2 } }),
      decision({ metric: "d", status: "insufficient_data", result: null }),
      decision({ metric: "e", status: "warn", result: null }),
    ];
    const by = (sort: "status" | "delta" | "metric") =>
      applyDiff(rows, { sort, slice: "", page: 1 }).rows.map((r) => r.metric);
    expect(by("status")).toEqual(["c", "a", "e", "b", "d"]);
    expect(by("delta")).toEqual(["c", "b", "a", "e", "d"]);
    expect(by("metric")).toEqual(["a", "b", "c", "d", "e"]);
  });
  it("filters by slice dimension and pages by 50", () => {
    const rows = Array.from({ length: 120 }, (_, i) =>
      decision({
        metric: `m${String(i).padStart(3, "0")}`,
        dimension: i % 2 === 0 ? "tenant" : "lang",
        value: "x",
      }),
    );
    expect(applyDiff(rows, { sort: "metric", slice: "tenant", page: 1 }).total).toBe(60);
    const all = applyDiff(rows, { sort: "metric", slice: "", page: 3 });
    expect([all.rows.length, all.pages, all.page]).toEqual([20, 3, 3]);
  });
  it("query round-trip; defaults are omitted; junk falls back", () => {
    expect(toDiffQuery({ sort: "status", slice: "", page: 1 })).toBe("");
    const s = { sort: "delta", slice: "tenant", page: 2 } as const;
    expect(parseDiffQuery(toDiffQuery(s))).toEqual(s);
    expect(parseDiffQuery("sort=zzz&page=0")).toEqual({ sort: "status", slice: "", page: 1 });
  });
  it("domain covers ci_low, ci_high, −max_drop and 0, padded 10 %; count splits testable", () => {
    const rows = [
      decision({ result: { ...RESULT, ci_low: -0.2, ci_high: -0.1 }, max_drop: 0.05 }),
      decision({ status: "insufficient_data", result: null }),
    ];
    const [lo, hi] = ciDomain(rows);
    expect(lo).toBeCloseTo(-0.22, 10);
    expect(hi).toBeCloseTo(0.02, 10);
    expect(countRows(rows)).toEqual({ testable: 1, insufficient: 1 });
    expect(ciDomain([])).toEqual([-1, 1]);
  });
});

describe("slices model", () => {
  it("groups by the §11.1 rule: gated without reason → gated, everything else informational", () => {
    expect(groupOf(sliceRow({ gated: true }))).toBe("gated");
    expect(groupOf(sliceRow({ gated: true, informational_reason: "judge_drift" }))).toBe(
      "informational",
    );
    expect(
      groupOf(
        sliceRow({
          gated: false,
          kind: "absolute",
          informational_reason: "tier1_injection_reported",
        }),
      ),
    ).toBe("informational");
    expect(groupOf(sliceRow({ gated: false, kind: "informational", notable: true }))).toBe(
      "informational",
    );
  });
  it("tier 2 has two sections, every row once", async () => {
    const rows = [
      sliceRow({ value: "a" }),
      sliceRow({
        value: "b",
        gated: false,
        kind: "informational",
        informational_reason: "judge_drift",
      }),
      sliceRow({ value: "c", gated: false, kind: "informational", notable: true }),
    ];
    const sections = sectionsFor(rows, "a40");
    expect(sections.map((s) => s.id)).toEqual(["gated", "informational"]);
    expect(sections.flatMap((s) => s.rows)).toHaveLength(3);
  });
  it("tier 1 (F-T1) has exactly three sections in order; every row once (UI11-01)", async () => {
    const rows = (await loadSlicesOf(IDS.tier1)).rows;
    const sections = sectionsFor(rows, "live");
    expect(sections.map((s) => s.id)).toEqual(["checks", "reported", "informational"]);
    expect(sections.flatMap((s) => s.rows)).toHaveLength(rows.length);
    const [checks, reported, info] = sections;
    expect(checks?.rows.every((r) => r.metric === "error_rate" && r.value === "overall")).toBe(
      true,
    );
    const reasons = new Set(reported?.rows.map((r) => r.informational_reason));
    expect([...reasons].sort()).toEqual(["tier1_deterministic_only", "tier1_injection_reported"]);
    expect(info?.rows.every((r) => r.informational_reason == null)).toBe(true);
  });
  it("orders bars worst first (status, mean_diff asc, value asc); null mean_diff last", () => {
    const rows = [
      sliceRow({ value: "z", status: "pass", mean_diff: -0.3 }),
      sliceRow({ value: "y", status: "fail", mean_diff: -0.1 }),
      sliceRow({ value: "x", status: "fail", mean_diff: -0.4 }),
      sliceRow({ value: "w", status: "fail", mean_diff: null }),
      sliceRow({ value: "v", status: "insufficient_data", mean_diff: -0.9 }),
    ];
    expect(chartRows(rows, "tenant", "context_recall").map((r) => r.value)).toEqual([
      "x",
      "y",
      "w",
      "z",
      "v",
    ]);
    expect(MAX_BARS).toBe(12);
  });
  it("per-section query: default dimension is the first non-overall one, metric 'all'; round-trips", () => {
    const rows = [
      sliceRow({ dimension: "overall", value: "overall" }),
      sliceRow({ dimension: "lang", value: "de", metric: "faithfulness" }),
      sliceRow({ dimension: "tenant", value: "k", metric: "context_recall" }),
      sliceRow({
        dimension: "overall",
        value: "overall",
        gated: false,
        kind: "informational",
        informational_reason: "judge_drift",
      }),
    ];
    const sections = sectionsFor(rows, "a40");
    const d = parseSlicesQuery("", sections);
    expect(d["gated"]).toEqual({ dimension: "tenant", metric: "" });
    expect(d["informational"]).toEqual({ dimension: "overall", metric: "" });
    expect(toSlicesQuery(d, sections)).toBe("");
    const s = { ...d, gated: { dimension: "lang", metric: "faithfulness" } };
    expect(parseSlicesQuery(toSlicesQuery(s, sections), sections)).toEqual(s);
    expect(toSlicesQuery(s, sections)).toBe("d_gated=lang&m_gated=faithfulness");
    expect(parseSlicesQuery("d_gated=nope&m_gated=zzz", sections)).toEqual(d);
  });
  it("populated: only compared runs have slices.json (the index agrees with the files)", async () => {
    const runs = await indexOf();
    expect(runs.some((r) => r.run_id === IDS.noBaseline && r.no_baseline === true)).toBe(true);
  });
});
