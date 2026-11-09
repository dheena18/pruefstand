import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportLink } from "@/components/ReportLink";
import { RunSubNav } from "@/components/RunSubNav";

const base = {
  locale: "en",
  runId: "r1",
  active: "summary",
  failing: 3,
  gated: true,
  noBaseline: false,
  casesPublished: true,
} as const;

describe("RunSubNav", () => {
  it("links all four tabs and marks the active one", () => {
    render(<RunSubNav {...base} />);
    expect(screen.getByRole("link", { name: "Summary" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Diff" })).toHaveAttribute("href", "/en/runs/r1/diff/");
    expect(screen.getByRole("link", { name: "Cases (3 failing)" })).toHaveAttribute(
      "href",
      "/en/runs/r1/cases/",
    );
  });
  it("Diff and Slices without gate.json: disabled '(not gated)'", () => {
    render(<RunSubNav {...base} gated={false} />);
    expect(screen.queryByRole("link", { name: /Diff/ })).toBeNull();
    const diff = screen.getByText(/^Diff/);
    expect(diff).toHaveAttribute("aria-disabled", "true");
    expect(diff).toHaveTextContent("(not gated)");
  });
  it("no_baseline: disabled '(nothing compared)' (UI11-20)", () => {
    render(<RunSubNav {...base} noBaseline locale="de" />);
    expect(screen.getByText(/^Vergleich/)).toHaveTextContent("(nichts verglichen)");
    expect(screen.getByText(/^Slices/)).toHaveAttribute("aria-disabled", "true");
  });
  it("S-CASES-PRUNED: Cases is an aria-disabled span '(cases not published)', no link", () => {
    render(<RunSubNav {...base} casesPublished={false} />);
    expect(screen.queryByRole("link", { name: /Cases/ })).toBeNull();
    const cases = screen.getByText(/^Cases/);
    expect(cases.tagName).toBe("SPAN");
    expect(cases).toHaveAttribute("aria-disabled", "true");
    expect(cases).toHaveTextContent("Cases (cases not published)");
  });
});

describe("ReportLink", () => {
  const props = {
    locale: "en",
    runId: "r1",
    basePath: "/pruefstand",
    status: "pass",
    casesPublished: true,
  } as const;
  it("renders plain <a> elements with the basePath, open and download (UI12-09)", () => {
    render(<ReportLink {...props} />);
    const open = screen.getByRole("link", { name: /Open HTML report/ });
    const dl = screen.getByRole("link", { name: "Download HTML report" });
    expect(open).toHaveAttribute("href", "/pruefstand/data/runs/r1/report.html");
    expect(dl).toHaveAttribute("download");
    expect(open.tagName).toBe("A");
  });
  it("renders nothing without a gate report or for an S-CASES-PRUNED run (N5.1)", () => {
    const { container, rerender } = render(<ReportLink {...props} status={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ReportLink {...props} casesPublished={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
