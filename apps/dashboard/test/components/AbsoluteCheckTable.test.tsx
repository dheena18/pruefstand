import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { AbsoluteCheckTable } from "@/components/AbsoluteCheckTable";
import { InformationalTable } from "@/components/InformationalTable";
import { JudgedInfoTable } from "@/components/JudgedInfoTable";
import type { LabelsDocument } from "@/lib/types";

import { decision, labelsOf } from "../fixtures";

let labels: LabelsDocument;
beforeAll(async () => {
  labels = await labelsOf();
});

const check = decision({
  metric: "error_rate",
  max_value: 0.02,
  max_drop: null,
  candidate_mean: 0,
  baseline_mean: 0,
  mde: null,
  result: null,
});

describe("AbsoluteCheckTable", () => {
  it("tier 2: Max = max_value", () => {
    render(<AbsoluteCheckTable locale="en" labels={labels} rows={[check]} variant="tier2" />);
    const row = screen.getAllByRole("row")[1];
    expect(row).toHaveTextContent("Error rate");
    expect(row).toHaveTextContent("0.00");
    expect(row).toHaveTextContent("0.02");
    expect(row).toHaveTextContent("PASS");
  });
  it("tier 1: the hard-fail row with its count comes first, then block C", () => {
    render(
      <AbsoluteCheckTable
        locale="en"
        labels={labels}
        rows={[check]}
        variant="tier1"
        hardFailCount={3}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Hard fails (canary, tenant, system prompt)");
    expect(rows[0]).toHaveTextContent("3");
    expect(rows[0]).toHaveTextContent("FAIL");
    expect(rows[1]).toHaveTextContent("Error rate");
  });
  it("tier 1 with no hard fails is PASS", () => {
    render(
      <AbsoluteCheckTable
        locale="de"
        labels={labels}
        rows={[]}
        variant="tier1"
        hardFailCount={0}
      />,
    );
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("PASS");
  });
});

const info = (over = {}) =>
  decision({
    metric: "refusal_correct",
    gated: false,
    status: "pass",
    informational_reason: "refusal_outside_nightly_full",
    ...over,
  });

describe("InformationalTable", () => {
  it("shows reason labels (en from labels.json, de from de.json), no status word, caption does-not-block", () => {
    const { rerender } = render(<InformationalTable locale="en" labels={labels} rows={[info()]} />);
    expect(screen.getByRole("table")).toHaveAccessibleName(/does not block/);
    expect(screen.getByText("refusal gated only in nightly full")).toBeInTheDocument();
    expect(screen.queryByText("PASS")).toBeNull();
    rerender(<InformationalTable locale="de" labels={labels} rows={[info()]} />);
    expect(
      screen.getByText("Ablehnung wird nur im nächtlichen Volllauf bewertet"),
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveAccessibleName(/blockiert nicht/);
  });
  it("shows an unknown reason code raw in mono", () => {
    render(
      <InformationalTable
        locale="en"
        labels={labels}
        rows={[info({ informational_reason: "brand_new" })]}
      />,
    );
    expect(screen.getByText("brand_new")).toHaveClass("mono");
  });
  it("adds dimension=value for a slice row and renders nothing without rows", () => {
    const { container, rerender } = render(
      <InformationalTable
        locale="en"
        labels={labels}
        rows={[info({ dimension: "lang", value: "de" })]}
      />,
    );
    expect(container).toHaveTextContent("lang=de");
    rerender(<InformationalTable locale="en" labels={labels} rows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("JudgedInfoTable", () => {
  const judged = decision({
    metric: "faithfulness",
    gated: false,
    informational_reason: "tier1_judged",
    baseline_mean: 0.88,
    candidate_mean: 0.85,
  });
  it("shows judged rows with the source and judged cases", () => {
    render(
      <JudgedInfoTable
        locale="en"
        labels={labels}
        rows={[judged]}
        judgeMode="github"
        judgedCases={10}
        judgedSubset={false}
      />,
    );
    expect(screen.getByRole("table")).toHaveAccessibleName(
      "Judged metrics — informational, does not block (GitHub Models, 10 cases)",
    );
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("Faithfulness");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("10");
    expect(screen.queryByText("PASS")).toBeNull();
  });
  it("names the judged subset after the heading (UI13-19)", () => {
    render(
      <JudgedInfoTable
        locale="en"
        labels={labels}
        rows={[judged]}
        judgeMode="local"
        judgedCases={150}
        judgedSubset
      />,
    );
    expect(screen.getByRole("table")).toHaveAccessibleName(
      /local judge \(A40\), 150 cases\) · judged subset \(150 cases\)/,
    );
  });
  it("judge_mode skipped → skipped text, no numbers", () => {
    const { container } = render(
      <JudgedInfoTable
        locale="de"
        labels={labels}
        rows={[judged]}
        judgeMode="skipped"
        judgedCases={0}
        judgedSubset={false}
      />,
    );
    expect(container).toHaveTextContent("Judge übersprungen");
    expect(container.querySelector("table")).toBeNull();
    expect(container).not.toHaveTextContent("0,85");
  });
});
