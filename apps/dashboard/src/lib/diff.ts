import type { RunContext } from "@/lib/run-context";
import type { SliceDecision } from "@/lib/types";

import { partition } from "./summary";

/**
 * The Diff page (ui-spec §4.3): which rows it shows and in which order. Block-G rows only (the Gated table of
 * §11.1); sort and slice filter come from the URL. Ordering and counting rows is presentation, not statistics.
 */

export const DIFF_PAGE_SIZE = 50;
export const DIFF_SORTS = ["status", "delta", "metric"] as const;
export type DiffSort = (typeof DIFF_SORTS)[number];

export interface DiffState {
  sort: DiffSort;
  /** Dimension to show (`tenant`, `lang`, …); empty = all. */
  slice: string;
  page: number;
}

export interface DiffModel {
  /** Block-G rows (tier 2); empty for a tier-1 run. */
  rows: SliceDecision[];
  /** Tier-1 block R rows (the reported table). */
  reported: SliceDecision[];
  /** Set for a tier-1 run: the notice data. */
  tier1: { splits: string[]; n: number } | null;
}

/** Rows of the diff page for one run context (the run must have a `gate.json`). */
export function buildDiffModel(ctx: RunContext): DiffModel {
  const blocks = ctx.gate === null ? null : partition(ctx.gate, ctx.run.stack);
  const tier1 = ctx.run.stack === "live" ? { splits: ctx.run.splits, n: ctx.run.n_cases } : null;
  return {
    rows: tier1 === null ? (blocks?.G ?? []) : [],
    reported: tier1 === null ? [] : (blocks?.R ?? []),
    tier1,
  };
}

export const DEFAULT_DIFF: DiffState = { sort: "status", slice: "", page: 1 };

/** Parse `?sort=status|delta|metric&slice=<dimension>&page=`; junk falls back to the default view. */
export function parseDiffQuery(query: string): DiffState {
  const params = new URLSearchParams(query);
  const sort = params.get("sort");
  const page = Number(params.get("page"));
  return {
    sort: (DIFF_SORTS as readonly string[]).includes(sort ?? "")
      ? (sort as DiffSort)
      : DEFAULT_DIFF.sort,
    slice: params.get("slice") ?? "",
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

export function toDiffQuery(state: DiffState): string {
  const params = new URLSearchParams();
  if (state.sort !== DEFAULT_DIFF.sort) params.set("sort", state.sort);
  if (state.slice !== "") params.set("slice", state.slice);
  if (state.page !== 1) params.set("page", String(state.page));
  return params.toString();
}

const STATUS_RANK: Record<string, number> = {
  fail: 0,
  warn: 1,
  unsupported_config: 2,
  pass: 3,
  insufficient_data: 4,
};
const rank = (d: SliceDecision): number => STATUS_RANK[d.status] ?? 5;
/** Δ ascending (most negative first); a row without a result sorts last. */
const delta = (d: SliceDecision): number => d.result?.mean_diff ?? Number.POSITIVE_INFINITY;
const cmp = (a: string, b: string): number => (a === b ? 0 : a < b ? -1 : 1);

function compareRows(a: SliceDecision, b: SliceDecision, sort: DiffSort): number {
  const byStatus = rank(a) - rank(b);
  const byDelta = delta(a) === delta(b) ? 0 : delta(a) < delta(b) ? -1 : 1;
  const byName = cmp(a.metric, b.metric) || cmp(a.dimension, b.dimension) || cmp(a.value, b.value);
  if (sort === "delta") return byDelta || byStatus || byName;
  if (sort === "metric") return byName || byStatus || byDelta;
  return byStatus || byDelta || byName;
}

export interface DiffPage {
  rows: SliceDecision[];
  total: number;
  page: number;
  pages: number;
}

/** Filter by slice dimension, sort, and cut the page (50 rows per chart). */
export function applyDiff(rows: readonly SliceDecision[], state: DiffState): DiffPage {
  const all = rows
    .filter((d) => state.slice === "" || d.dimension === state.slice)
    .sort((a, b) => compareRows(a, b, state.sort));
  const pages = Math.max(1, Math.ceil(all.length / DIFF_PAGE_SIZE));
  const page = Math.min(state.page, pages);
  return {
    rows: all.slice((page - 1) * DIFF_PAGE_SIZE, page * DIFF_PAGE_SIZE),
    total: all.length,
    page,
    pages,
  };
}

/** The dimensions present among the rows, in order of first appearance. */
export const sliceOptions = (rows: readonly SliceDecision[]): string[] => [
  ...new Set(rows.map((d) => d.dimension)),
];

/** `testable` = rows with a CI and a status other than INSUFFICIENT_DATA; `insufficient` = the others by status. */
export function countRows(rows: readonly SliceDecision[]): {
  testable: number;
  insufficient: number;
} {
  const insufficient = rows.filter((d) => d.status === "insufficient_data").length;
  return {
    testable: rows.filter((d) => d.status !== "insufficient_data" && d.result !== null).length,
    insufficient,
  };
}

/**
 * Shared x scale (ui-spec §4.3): min and max of `ci_low`, `ci_high`, `−max_drop` and 0 (so the zero line is
 * always visible), padded by 10 %. INSUFFICIENT_DATA rows draw no CI and do not widen it.
 */
export function ciDomain(rows: readonly SliceDecision[]): [number, number] {
  const values: number[] = [0];
  for (const d of rows) {
    if (d.max_drop != null) values.push(-d.max_drop);
    if (d.result !== null && d.status !== "insufficient_data")
      values.push(d.result.ci_low, d.result.ci_high);
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (rows.length === 0 || lo === hi) return [-1, 1];
  const pad = (hi - lo) * 0.1;
  return [lo - pad, hi + pad];
}
