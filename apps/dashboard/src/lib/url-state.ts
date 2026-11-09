import type { RunIndexEntry } from "@/lib/types";

import { refKey } from "./format";

/** Runs-list state in the URL query (ui-spec §4.1, UI-24): filters, sort and page. */

export const PAGE_SIZE = 25;
export const STATUS_VALUES = [
  "pass",
  "warn",
  "fail",
  "insufficient_data",
  "unsupported_config",
  "no_baseline",
  "not_gated",
] as const;
export const TIER_VALUES = ["1", "2"] as const;
export const WORKLOAD_VALUES = ["pr", "nightly", "bench"] as const;
export const SORT_KEYS = ["created", "status", "duration", "cost"] as const;

export type StatusKey = (typeof STATUS_VALUES)[number];
export type SortKey = (typeof SORT_KEYS)[number];

export interface ListState {
  status: StatusKey | "";
  ref: string;
  tier: (typeof TIER_VALUES)[number] | "";
  workload: (typeof WORKLOAD_VALUES)[number] | "";
  sort: SortKey;
  dir: "asc" | "desc";
  page: number;
}

export const DEFAULT_STATE: ListState = {
  status: "",
  ref: "",
  tier: "",
  workload: "",
  sort: "created",
  dir: "desc",
  page: 1,
};

function oneOf<T extends string>(values: readonly T[], raw: string | null): T | "" {
  return raw !== null && (values as readonly string[]).includes(raw) ? (raw as T) : "";
}

/** Parse a query string (with or without `?`); unknown values fall back to the default view. */
export function parseQuery(query: string): ListState {
  const params = new URLSearchParams(query);
  const page = Number(params.get("page"));
  return {
    status: oneOf(STATUS_VALUES, params.get("status")),
    ref: params.get("ref") ?? "",
    tier: oneOf(TIER_VALUES, params.get("tier")),
    workload: oneOf(WORKLOAD_VALUES, params.get("workload")),
    sort: oneOf(SORT_KEYS, params.get("sort")) || DEFAULT_STATE.sort,
    dir: params.get("dir") === "asc" ? "asc" : "desc",
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

/** The query string of a state; defaults are omitted, so the default view has an empty query. */
export function toQuery(state: ListState): string {
  const params = new URLSearchParams();
  for (const key of ["status", "ref", "tier", "workload"] as const) {
    if (state[key] !== "") params.set(key, state[key]);
  }
  if (state.sort !== DEFAULT_STATE.sort) params.set("sort", state.sort);
  if (state.dir !== DEFAULT_STATE.dir) params.set("dir", state.dir);
  if (state.page !== 1) params.set("page", String(state.page));
  return params.toString();
}

/** A filter change resets the page to 1 (ui-spec §4.1). */
export function withFilter(
  state: ListState,
  patch: Partial<Pick<ListState, "status" | "ref" | "tier" | "workload">>,
): ListState {
  return { ...state, ...patch, page: 1 };
}

/** The status the list row shows, which the status filter matches (UI11-19). */
export function statusKey(run: RunIndexEntry): StatusKey {
  if (run.no_baseline === true) return "no_baseline";
  return run.status ?? "not_gated";
}

const STATUS_RANK: Record<StatusKey, number> = {
  fail: 0,
  no_baseline: 1,
  warn: 2,
  unsupported_config: 3,
  insufficient_data: 4,
  pass: 5,
  not_gated: 6,
};

function compare(a: RunIndexEntry, b: RunIndexEntry, key: SortKey): number {
  switch (key) {
    case "status":
      return STATUS_RANK[statusKey(a)] - STATUS_RANK[statusKey(b)];
    case "duration":
      return a.duration_s - b.duration_s;
    case "cost":
      return a.cost_usd - b.cost_usd;
    case "created":
      return Date.parse(a.created_at) - Date.parse(b.created_at);
  }
}

export interface ListView {
  rows: RunIndexEntry[];
  total: number;
  page: number;
  pages: number;
  from: number;
  to: number;
}

function matches(run: RunIndexEntry, state: ListState): boolean {
  if (state.status !== "" && statusKey(run) !== state.status) return false;
  if (state.ref !== "" && refKey(run) !== state.ref) return false;
  if (state.tier !== "" && (run.stack === "live" ? "1" : "2") !== state.tier) return false;
  return state.workload === "" || run.workload === state.workload;
}

/** Filter, sort (ties by `run_id` asc) and page the index. Presentation only. */
export function applyState(runs: readonly RunIndexEntry[], state: ListState): ListView {
  const sign = state.dir === "asc" ? 1 : -1;
  const rows = runs
    .filter((run) => matches(run, state))
    .sort((a, b) => sign * compare(a, b, state.sort) || a.run_id.localeCompare(b.run_id));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(state.page, pages);
  const start = (page - 1) * PAGE_SIZE;
  return {
    rows: rows.slice(start, start + PAGE_SIZE),
    total: rows.length,
    page,
    pages,
    from: rows.length === 0 ? 0 : start + 1,
    to: Math.min(start + PAGE_SIZE, rows.length),
  };
}
