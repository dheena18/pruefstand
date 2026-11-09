import type { DashboardCase } from "@/lib/types";

import { compareCases } from "./cases";

/**
 * Cases-list state in the URL query (ui-spec §4.5.2): `?failing=1&tenant=&category=&lang=&perturbation=&q=&page=&case=`.
 * Filtering, searching, sorting and paging run over the loaded rows; nothing here computes a metric.
 */

export const CASE_PAGE_SIZE = 25;

export interface CasesState {
  /** Only `failing == true` rows. */
  failing: boolean;
  tenant: string;
  category: string;
  lang: string;
  perturbation: string;
  /** Search over case id and question. */
  q: string;
  page: number;
  /** Selected case id (detail panel); empty = none. */
  case: string;
}

export type Facet = "tenant" | "category" | "lang" | "perturbation";
const TEXT_KEYS = ["tenant", "category", "lang", "perturbation", "q", "case"] as const;

/**
 * Parse a query string. Without `failing` the default view is "Failing only" when the run has a failing case
 * (`hasFailing`), else all cases; `failing=0` / `failing=1` override it.
 */
export function parseCasesQuery(query: string, hasFailing: boolean): CasesState {
  const params = new URLSearchParams(query);
  const raw = params.get("failing");
  const page = Number(params.get("page"));
  return {
    failing: raw === "1" ? true : raw === "0" ? false : hasFailing,
    tenant: params.get("tenant") ?? "",
    category: params.get("category") ?? "",
    lang: params.get("lang") ?? "",
    perturbation: params.get("perturbation") ?? "",
    q: params.get("q") ?? "",
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    case: params.get("case") ?? "",
  };
}

/** The query string of a state; defaults are omitted, so the default view has an empty query. */
export function toCasesQuery(state: CasesState, hasFailing: boolean): string {
  const params = new URLSearchParams();
  if (state.failing !== hasFailing) params.set("failing", state.failing ? "1" : "0");
  for (const key of TEXT_KEYS) if (state[key] !== "") params.set(key, state[key]);
  if (state.page !== 1) params.set("page", String(state.page));
  return params.toString();
}

/** A filter or search change goes back to page 1 and keeps the selected case. */
export function withCasesFilter(
  state: CasesState,
  patch: Partial<Omit<CasesState, "page">>,
): CasesState {
  return { ...state, ...patch, page: 1 };
}

/** The cases that match the state, in the R4 order (failing first, then `case_id`). */
export function filterCases(rows: readonly DashboardCase[], state: CasesState): DashboardCase[] {
  const q = state.q.trim().toLowerCase();
  return rows
    .filter((c) => !state.failing || c.failing)
    .filter((c) => state.tenant === "" || c.tenant === state.tenant)
    .filter((c) => state.category === "" || c.category === state.category)
    .filter((c) => state.lang === "" || c.lang === state.lang)
    .filter((c) => state.perturbation === "" || c.perturbation === state.perturbation)
    .filter(
      (c) =>
        q === "" || c.case_id.toLowerCase().includes(q) || c.question.toLowerCase().includes(q),
    )
    .sort(compareCases);
}

export interface CasesPage {
  rows: DashboardCase[];
  total: number;
  page: number;
  pages: number;
  from: number;
  to: number;
}

/** Filter, sort and page (25 per page; a page past the end is clamped). */
export function applyCases(rows: readonly DashboardCase[], state: CasesState): CasesPage {
  const all = filterCases(rows, state);
  const pages = Math.max(1, Math.ceil(all.length / CASE_PAGE_SIZE));
  const page = Math.min(state.page, pages);
  const start = (page - 1) * CASE_PAGE_SIZE;
  return {
    rows: all.slice(start, start + CASE_PAGE_SIZE),
    total: all.length,
    page,
    pages,
    from: all.length === 0 ? 0 : start + 1,
    to: Math.min(start + CASE_PAGE_SIZE, all.length),
  };
}

/** Distinct non-empty values of a facet among the rows, sorted. */
export function facetValues(rows: readonly DashboardCase[], facet: Facet): string[] {
  const values = new Set<string>();
  for (const row of rows) {
    const value = row[facet];
    if (value != null && value !== "") values.add(value);
  }
  return [...values].sort();
}

/** Failing rows are all in shard 0 (R4): the count of the build-time shard. */
export const failingCount = (rows: readonly DashboardCase[]): number =>
  rows.filter((c) => c.failing).length;
