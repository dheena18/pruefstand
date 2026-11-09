import type { DashboardSliceRow } from "@/lib/types";

import { assignBlock, assignTable, type Block, type Source, type Stack } from "./tables";

/**
 * The Slices page (ui-spec §4.4): grouping by the one table rule of §11.1, bar order, and the per-section
 * dimension / metric choice in the URL. Rows are assigned and ordered, never computed.
 */

export const MAX_BARS = 12;
export type SectionId = "gated" | "informational" | "checks" | "reported";
export interface Section {
  id: SectionId;
  rows: DashboardSliceRow[];
}

/** Which `gate.json` list a slice row came from, derived from `kind` (interfaces §10.1). */
function sourceOf(row: DashboardSliceRow): Source {
  if (row.kind === "absolute") return "absolute_checks";
  return row.kind === "informational" && row.informational_reason == null
    ? "notable_slices"
    : "decisions";
}

/** The §11.1 group of a row: `gated and informational_reason is None` → Gated; everything else Informational. */
export const groupOf = (row: DashboardSliceRow): "gated" | "informational" =>
  assignTable(row, sourceOf(row)) === "gated" ? "gated" : "informational";

/** The layout block of a row (G/A/C/R/J/I/N) for the run's tier. */
export const blockOf = (row: DashboardSliceRow, stack: Stack): Block =>
  assignBlock(row, sourceOf(row), stack);

const TIER1_ORDER: Record<Block, SectionId> = {
  G: "checks",
  A: "checks",
  C: "checks",
  R: "reported",
  J: "informational",
  I: "informational",
  N: "informational",
};

/**
 * Sections in page order. Tier 2: Gated, Informational. Tier 1 (UI11-01): `checks` (the Gated group),
 * `reported` (block R), `informational` (blocks J, I, N). Every row is in exactly one section; empty ones are kept
 * out, except that tier 1 always lists its three sections that have rows.
 */
export function sectionsFor(rows: readonly DashboardSliceRow[], stack: Stack): Section[] {
  const order: SectionId[] =
    stack === "live" ? ["checks", "reported", "informational"] : ["gated", "informational"];
  const sections: Section[] = order.map((id) => ({ id, rows: [] }));
  for (const row of rows) {
    const id = stack === "live" ? TIER1_ORDER[blockOf(row, stack)] : groupOf(row);
    sections.find((s) => s.id === id)?.rows.push(row);
  }
  return sections.filter((s) => s.rows.length > 0);
}

const DIMENSION_ORDER = ["tenant", "lang", "category", "perturbation", "perturbed_all", "tags"];

/** Dimensions of a set of rows: the known ones in a fixed order, then others, `overall` last. */
export function dimensionsOf(rows: readonly DashboardSliceRow[]): string[] {
  const present = new Set(rows.map((r) => r.dimension));
  const known = DIMENSION_ORDER.filter((d) => present.has(d));
  const other = [...present].filter((d) => d !== "overall" && !DIMENSION_ORDER.includes(d)).sort();
  return [...known, ...other, ...(present.has("overall") ? ["overall"] : [])];
}

/** Metrics of the rows of one dimension, in order of first appearance. */
export function metricsOf(rows: readonly DashboardSliceRow[], dimension: string): string[] {
  return [...new Set(rows.filter((r) => r.dimension === dimension).map((r) => r.metric))];
}

export interface SectionState {
  dimension: string;
  /** Empty = one chart per metric. */
  metric: string;
}
export type SlicesState = Partial<Record<SectionId, SectionState>>;

const defaultDimension = (rows: readonly DashboardSliceRow[]): string =>
  dimensionsOf(rows)[0] ?? "overall";

/** Per section: `?d_<id>=<dimension>&m_<id>=<metric>`; an unknown value falls back to the default. */
export function parseSlicesQuery(query: string, sections: readonly Section[]): SlicesState {
  const params = new URLSearchParams(query);
  const state: SlicesState = {};
  for (const { id, rows } of sections) {
    const wanted = params.get(`d_${id}`) ?? "";
    const dimension = dimensionsOf(rows).includes(wanted) ? wanted : defaultDimension(rows);
    const metric = params.get(`m_${id}`) ?? "";
    state[id] = { dimension, metric: metricsOf(rows, dimension).includes(metric) ? metric : "" };
  }
  return state;
}

export function toSlicesQuery(state: SlicesState, sections: readonly Section[]): string {
  const params = new URLSearchParams();
  for (const { id, rows } of sections) {
    const s = state[id];
    if (s === undefined) continue;
    if (s.dimension !== defaultDimension(rows)) params.set(`d_${id}`, s.dimension);
    if (s.metric !== "") params.set(`m_${id}`, s.metric);
  }
  return params.toString();
}

const STATUS_RANK: Record<string, number> = {
  fail: 0,
  warn: 1,
  unsupported_config: 2,
  pass: 3,
  insufficient_data: 4,
};
const cmp = (a: string, b: string): number => (a === b ? 0 : a < b ? -1 : 1);

/** Rows of one (dimension, metric), worst first: status order, then `mean_diff` ascending (null last), then value. */
export function chartRows(
  rows: readonly DashboardSliceRow[],
  dimension: string,
  metric: string,
): DashboardSliceRow[] {
  const diff = (r: DashboardSliceRow): number => r.mean_diff ?? Number.POSITIVE_INFINITY;
  return rows
    .filter((r) => r.dimension === dimension && r.metric === metric)
    .sort(
      (a, b) =>
        (STATUS_RANK[a.status] ?? 5) - (STATUS_RANK[b.status] ?? 5) ||
        (diff(a) === diff(b) ? 0 : diff(a) < diff(b) ? -1 : 1) ||
        cmp(a.value, b.value),
    );
}
