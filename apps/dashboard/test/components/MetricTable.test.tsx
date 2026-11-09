import { render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { MetricTable } from "@/components/MetricTable";
import type { LabelsDocument } from "@/lib/types";

import { decision, labelsOf } from "../fixtures";

let labels: LabelsDocument;
beforeAll(async () => {
  labels = await labelsOf();
});

const rows = () => [
  decision({ metric: "faithfulness", status: "pass", baseline_mean: 0.91, candidate_mean: 0.9 }),
  decision({ metric: "context_recall", status: "fail" }),
  decision({ metric: "citation_f1", status: "insufficient_data", max_drop: null, mde: null }),
  decision({ metric: "language_match", status: "warn" }),
];

describe("MetricTable gated variant", () => {
  it("sorts FAIL → WARN → PASS → INSUFFICIENT_DATA and has the 7 columns", () => {
    render(
      <MetricTable
        locale="en"
        labels={labels}
        rows={rows()}
        variant="gated"
        caption="Gated metrics (overall)"
      />,
    );
    const body = screen.getAllByRole("row").slice(1);
    const order = body.map((r) => within(r).getAllByRole("cell").at(-1)?.textContent);
    expect(order).toEqual(["FAIL", "WARN", "PASS", "INSUFFICIENT DATA"]);
    expect(screen.getAllByRole("columnheader")).toHaveLength(7);
  });
  it("shows Δ (CI), δ = max_drop, MDE with 2 decimals and Unicode minus", () => {
    render(
      <MetricTable locale="en" labels={labels} rows={[decision({})]} variant="gated" caption="c" />,
    );
    const row = screen.getAllByRole("row")[1];
    expect(row).toHaveTextContent("Context recall");
    expect(row).toHaveTextContent("0.86");
    expect(row).toHaveTextContent("0.77");
    expect(row).toHaveTextContent("−0.09 (−0.12, −0.06)");
    expect(row).toHaveTextContent("0.05");
    expect(row).toHaveTextContent("0.06");
  });
  it("renders – with a hidden 'no threshold' when max_drop is null", () => {
    render(
      <MetricTable
        locale="en"
        labels={labels}
        rows={[decision({ max_drop: null })]}
        variant="gated"
        caption="c"
      />,
    );
    expect(screen.getByText("no threshold")).toHaveClass("sr-only");
  });
  it("uses the decimal comma and the de label in de", () => {
    render(
      <MetricTable locale="de" labels={labels} rows={[decision({})]} variant="gated" caption="c" />,
    );
    const row = screen.getAllByRole("row")[1];
    expect(row).toHaveTextContent("Kontext-Recall");
    expect(row).toHaveTextContent("0,86");
    expect(row).toHaveTextContent("−0,09 (−0,12, −0,06)");
  });
});

describe("MetricTable reported variant (tier 1, block R)", () => {
  const reported = [
    decision({
      metric: "injection_success",
      gated: false,
      informational_reason: "tier1_injection_reported",
      max_value: 0.02,
      max_drop: null,
      mde: null,
      result: null,
      baseline_mean: 0,
      candidate_mean: 0,
    }),
  ];
  it("has Max and 'Reported because', no CI column and no status word", () => {
    render(
      <MetricTable
        locale="en"
        labels={labels}
        rows={reported}
        variant="reported"
        caption="Reported"
      />,
    );
    const heads = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["Metric", "Base", "PR", "Δ", "MDE", "Max", "Reason"]);
    const row = screen.getAllByRole("row")[1];
    expect(row).toHaveTextContent("injection reported in tier 1");
    expect(row).toHaveTextContent("0.02");
    expect(row).not.toHaveTextContent(/PASS|FAIL|WARN/);
  });
});
