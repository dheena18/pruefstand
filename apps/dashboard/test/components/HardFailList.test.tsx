import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { HardFailList } from "@/components/HardFailList";
import type { HardFailFinding, LabelsDocument } from "@/lib/types";

import { IDS, ctxOf, labelsOf } from "../fixtures";

let labels: LabelsDocument;
let findings: HardFailFinding[];
beforeAll(async () => {
  labels = await labelsOf();
  findings = (await ctxOf(IDS.hardFail)).gate?.hard_fails ?? [];
});

describe("HardFailList", () => {
  it("F-HARD-FAIL: rule label from labels.json on /en, rule.<code> on /de, never the raw code (UI12-15)", () => {
    const { container, rerender } = render(
      <HardFailList
        locale="en"
        labels={labels}
        runId="r1"
        hardFails={findings.slice(0, 1)}
        casesPublished
      />,
    );
    expect(screen.getByText("Tenant leak")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("hard_fail");
    rerender(
      <HardFailList
        locale="de"
        labels={labels}
        runId="r1"
        hardFails={findings.slice(0, 1)}
        casesPublished
      />,
    );
    expect(screen.getByText("Mandanten-Leck")).toBeInTheDocument();
  });
  it("lists case id, metric and the evidence in lang=de; hard fails come with a count heading", () => {
    render(
      <HardFailList
        locale="en"
        labels={labels}
        runId="r1"
        hardFails={findings.slice(0, 2)}
        casesPublished
      />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Hard fails (2)");
    const evidence = document.querySelector("q");
    expect(evidence).toHaveAttribute("lang", "de");
    expect(screen.getAllByText("slice-009").length).toBeGreaterThan(0);
  });
  it("a case-published run links each finding to its static case page", () => {
    render(
      <HardFailList
        locale="en"
        labels={labels}
        runId="r1"
        hardFails={findings.slice(0, 1)}
        casesPublished
      />,
    );
    expect(screen.getByRole("link", { name: /Open case/ })).toHaveAttribute(
      "href",
      "/en/runs/r1/cases/slice-009/",
    );
  });
  it("S-CASES-PRUNED: every finding keeps id and evidence but has no link (UI13-16)", () => {
    for (const variant of ["panel", "findings"] as const) {
      const { container, unmount } = render(
        <HardFailList
          locale="en"
          labels={labels}
          runId="r1"
          hardFails={findings.slice(0, 2)}
          casesPublished={false}
          variant={variant}
        />,
      );
      expect(container.querySelectorAll("a")).toHaveLength(0);
      expect(container).toHaveTextContent("slice-009");
      expect(container.querySelectorAll("q")).toHaveLength(2);
      unmount();
    }
  });
  it("does not link a redacted case id and shows an unknown rule raw", () => {
    const odd: HardFailFinding[] = [
      { case_id: "‹redacted›", evidence: "‹redacted›", metric: "new_metric", rule: "new_rule" },
    ];
    const { container } = render(
      <HardFailList locale="en" labels={labels} runId="r1" hardFails={odd} casesPublished />,
    );
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container).toHaveTextContent("new_rule");
  });
  it("renders nothing without findings", () => {
    const { container } = render(
      <HardFailList locale="en" labels={labels} runId="r" hardFails={[]} casesPublished />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
