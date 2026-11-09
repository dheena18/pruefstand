import type { SliceDecision } from "@/lib/types";

/** The two fields of a decision (or a `DashboardSliceRow`) that decide its table and block. */
export type Classified = Pick<SliceDecision, "gated" | "informational_reason">;

/**
 * One table rule for every `SliceDecision` (ui-spec §11.1, interfaces §9, X5.4). Mirrors
 * `pruefstand.report.tables` (T1.9): which of three tables a row belongs to, and which layout block.
 * Assigning a table is formatting, not metric computation.
 */

export type Source = "decisions" | "absolute_checks" | "notable_slices";
export type Stack = "live" | "a40";
export type Table = "gated" | "informational" | "notable";
export type Block = "G" | "A" | "C" | "R" | "J" | "I" | "N";

export const NO_REASON = "–";
export const REPORTED_REASONS: ReadonlySet<string> = new Set([
  "tier1_deterministic_only",
  "tier1_injection_reported",
  "applicable_clusters<30",
]);
export const JUDGED_REASON = "tier1_judged";

/** The `informational_reason` of a row, or `–` when it has none. */
export function reasonCode(decision: Pick<SliceDecision, "informational_reason">): string {
  return decision.informational_reason ?? NO_REASON;
}

/**
 * The one table a row belongs to (first match wins): Gated (`gated`, no reason; incl. INSUFFICIENT_DATA),
 * Informational (any reason), Notable (a `notable_slices` row matching neither). A row matching none is a
 * gate bug and is returned as Informational (reason `–`), never dropped.
 */
export function assignTable(decision: Classified, source: Source): Table {
  if (decision.informational_reason != null) return "informational";
  if (decision.gated) return "gated";
  return source === "notable_slices" ? "notable" : "informational";
}

/** The layout block of a row for the tier given by `stack`. */
export function assignBlock(decision: Classified, source: Source, stack: Stack): Block {
  const table = assignTable(decision, source);
  if (table === "notable") return "N";
  if (table === "gated") {
    if (source === "absolute_checks") return stack === "live" ? "C" : "A";
    return "G";
  }
  const reason = decision.informational_reason ?? undefined;
  if (stack === "live" && reason !== undefined && REPORTED_REASONS.has(reason)) return "R";
  if (stack === "live" && reason === JUDGED_REASON) return "J";
  return "I";
}
