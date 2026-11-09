import { describe, expect, it } from "vitest";

import type { RunIndexEntry } from "@/lib/types";
import {
  DEFAULT_STATE,
  PAGE_SIZE,
  applyState,
  parseQuery,
  statusKey,
  toQuery,
  withFilter,
} from "@/lib/url-state";

function run(over: Partial<RunIndexEntry> & { run_id: string }): RunIndexEntry {
  return {
    baseline_run_id: null,
    block: null,
    complete: true,
    cost_usd: 0,
    created_at: "2026-10-31T13:00:00Z",
    duration_s: 60,
    git_ref: "main",
    git_sha: "a1b2c3d4",
    judge_degraded: false,
    judge_drift: false,
    judge_fallback: false,
    judge_mode: "github",
    judged_subset: false,
    n_cases: 20,
    no_baseline: false,
    pr_number: null,
    stack: "live",
    status: "pass",
    stop_reason: "completed",
    workload: "pr",
    ...over,
  };
}

describe("parseQuery / toQuery", () => {
  it("round-trips filters, sort and page", () => {
    const state = {
      status: "fail",
      ref: "main",
      tier: "2",
      workload: "nightly",
      sort: "duration",
      dir: "asc",
      page: 3,
    } as const;
    const query = toQuery(state);
    expect(parseQuery(query)).toEqual(state);
  });
  it("omits defaults and gives the default view for an empty query", () => {
    expect(toQuery(DEFAULT_STATE)).toBe("");
    expect(parseQuery("")).toEqual(DEFAULT_STATE);
  });
  it("ignores unknown values", () => {
    const state = parseQuery("status=bogus&tier=9&workload=x&sort=nope&dir=up&page=-4");
    expect(state).toEqual(DEFAULT_STATE);
    expect(parseQuery("page=abc").page).toBe(1);
  });
  it("accepts a leading question mark", () => {
    expect(parseQuery("?status=warn").status).toBe("warn");
  });
});

describe("withFilter", () => {
  it("resets the page when a filter changes", () => {
    const state = withFilter({ ...DEFAULT_STATE, page: 4 }, { status: "pass" });
    expect(state.page).toBe(1);
    expect(state.status).toBe("pass");
  });
});

describe("statusKey (UI11-19)", () => {
  it("is no_baseline first, then not_gated, else the status", () => {
    expect(statusKey(run({ run_id: "a", no_baseline: true, status: "insufficient_data" }))).toBe(
      "no_baseline",
    );
    expect(statusKey(run({ run_id: "b", status: null }))).toBe("not_gated");
    expect(statusKey(run({ run_id: "c", status: "warn" }))).toBe("warn");
  });
});

describe("applyState", () => {
  const runs = [
    run({ run_id: "r1", no_baseline: true, status: "insufficient_data" }),
    run({ run_id: "r2", status: "insufficient_data", created_at: "2026-10-31T14:00:00Z" }),
    run({ run_id: "r3", status: null, stack: "a40", workload: "nightly" }),
    run({ run_id: "r4", status: "fail", git_ref: "refs/pull/4/merge", pr_number: 4 }),
  ];
  it("?status=insufficient_data excludes a no-baseline run, ?status=no_baseline includes it", () => {
    const a = applyState(runs, parseQuery("status=insufficient_data"));
    expect(a.rows.map((r) => r.run_id)).toEqual(["r2"]);
    const b = applyState(runs, parseQuery("status=no_baseline"));
    expect(b.rows.map((r) => r.run_id)).toEqual(["r1"]);
    expect(applyState(runs, parseQuery("status=not_gated")).rows.map((r) => r.run_id)).toEqual([
      "r3",
    ]);
  });
  it("filters by tier and workload", () => {
    expect(applyState(runs, parseQuery("tier=2")).rows.map((r) => r.run_id)).toEqual(["r3"]);
    expect(applyState(runs, parseQuery("workload=nightly")).total).toBe(1);
  });
  it("filters by ref label", () => {
    expect(applyState(runs, parseQuery("ref=pr-4")).rows.map((r) => r.run_id)).toEqual(["r4"]);
  });
  it("sorts created desc by default, ties by run_id asc", () => {
    const rows = applyState(runs, DEFAULT_STATE).rows.map((r) => r.run_id);
    expect(rows[0]).toBe("r2");
    expect(rows.slice(1)).toEqual(["r1", "r3", "r4"]);
  });
  it("sorts by status rank FAIL → NO BASELINE → … → NOT GATED", () => {
    const rows = applyState(runs, parseQuery("sort=status&dir=asc")).rows.map((r) => r.run_id);
    expect(rows).toEqual(["r4", "r1", "r2", "r3"]);
  });
  it("pages at 25 and clamps the page", () => {
    const many = Array.from({ length: 60 }, (_, i) =>
      run({ run_id: `x${String(i).padStart(2, "0")}` }),
    );
    const page3 = applyState(many, parseQuery("page=3"));
    expect(PAGE_SIZE).toBe(25);
    expect(page3.pages).toBe(3);
    expect(page3.rows).toHaveLength(10);
    expect(applyState(many, parseQuery("page=99")).page).toBe(3);
  });
});
