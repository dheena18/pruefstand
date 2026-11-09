import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import type { GateReport, SliceDecision } from "@/lib/types";
import { assignBlock, assignTable, reasonCode, type Source } from "@/lib/tables";

import cases from "./tables.cases.json";

function decision(over: Partial<SliceDecision>): SliceDecision {
  return {
    metric: "context_recall",
    dimension: "overall",
    value: "overall",
    status: "pass",
    gated: true,
    baseline_mean: 0.5,
    candidate_mean: 0.5,
    result: null,
    p_adjusted: null,
    mde: null,
    ...over,
  };
}

interface Case {
  name: string;
  source: Source;
  stack?: "live" | "a40";
  gated: boolean;
  reason: string | null;
  status?: SliceDecision["status"];
  table?: string;
  block?: string;
}

const build = (c: Case) =>
  decision({
    gated: c.gated,
    informational_reason: c.reason,
    ...(c.status === undefined ? {} : { status: c.status }),
  });

describe("assignTable (shared cases, interfaces §9)", () => {
  it.each(cases.assign_table as Case[])("$name", (c) => {
    expect(assignTable(build(c), c.source)).toBe(c.table);
  });
});

describe("assignBlock (shared cases)", () => {
  it.each(cases.assign_block as Case[])("$name", (c) => {
    expect(assignBlock(build(c), c.source, c.stack ?? "a40")).toBe(c.block);
  });
});

describe("reasonCode", () => {
  it("is the reason or an en dash", () => {
    expect(reasonCode(decision({ informational_reason: "judge_drift" }))).toBe("judge_drift");
    expect(reasonCode(decision({}))).toBe("–");
  });
});

describe("every decision of each fixture gate lands in exactly one table", () => {
  const runs = path.join(__dirname, "../../fixtures/populated/runs");
  const ids = [
    "20261103T123537-e01927",
    "20261103T124130-8ee0ce",
    "20261103T123737-95d79b",
    "20261103T123837-5d3b0f",
  ];
  it.each(ids)("%s", (id) => {
    const gate = JSON.parse(readFileSync(path.join(runs, id, "gate.json"), "utf8")) as GateReport;
    const rows: [SliceDecision, Source][] = [
      ...gate.decisions.map((d): [SliceDecision, Source] => [d, "decisions"]),
      ...gate.absolute_checks.map((d): [SliceDecision, Source] => [d, "absolute_checks"]),
      ...gate.notable_slices.map((d): [SliceDecision, Source] => [d, "notable_slices"]),
    ];
    const counts = { gated: 0, informational: 0, notable: 0 };
    for (const [d, source] of rows) counts[assignTable(d, source)] += 1;
    expect(counts.gated + counts.informational + counts.notable).toBe(rows.length);
  });
});
