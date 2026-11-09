import type { GateReport, SliceDecision } from "@/lib/types";

import { assignBlock, type Block, type Source, type Stack } from "./tables";

/**
 * Lays the rows of a `GateReport` out in the blocks of ui-spec §11.1 for the run summary. Every row goes
 * through `assignBlock`; counting and filtering list items is formatting, not metric computation.
 */

export type Partition = Record<Block, SliceDecision[]>;

const SOURCES: [Source, (g: GateReport) => SliceDecision[]][] = [
  ["decisions", (g) => g.decisions],
  ["absolute_checks", (g) => g.absolute_checks],
  ["notable_slices", (g) => g.notable_slices],
];

export function partition(gate: GateReport, stack: Stack): Partition {
  const out: Partition = { G: [], A: [], C: [], R: [], J: [], I: [], N: [] };
  for (const [source, rows] of SOURCES) {
    for (const row of rows(gate)) out[assignBlock(row, source, stack)].push(row);
  }
  return out;
}

/** Blocking issues = hard fails + FAIL rows of the Gated table (blocks G and A/C; ui-spec §4.2). */
export function blockingCount(gate: GateReport, blocks: Partition): number {
  const failing = [...blocks.G, ...blocks.A, ...blocks.C].filter((d) => d.status === "fail");
  return gate.hard_fails.length + failing.length;
}

export const isOverall = (d: SliceDecision): boolean => d.dimension === "overall";

/** Block I rows that carry a reason; a reason-less row is a slice-level absolute check shown on the Slices page. */
export const withReason = (rows: SliceDecision[]): SliceDecision[] =>
  rows.filter((d) => d.informational_reason != null);

/** `dimension=value` suffix of a non-overall row, or an empty string. */
export const sliceSuffix = (d: SliceDecision): string =>
  isOverall(d) ? "" : ` · ${d.dimension}=${d.value}`;
