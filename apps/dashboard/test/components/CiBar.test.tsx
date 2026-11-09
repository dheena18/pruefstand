import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CiBar } from "@/components/CiBar";

import { decision, RESULT } from "../fixtures";

const result = { ...RESULT, mean_diff: -0.07, ci_low: -0.1, ci_high: -0.04, confidence: 0.95 };
const fail = decision({ status: "fail", result, max_drop: 0.05 });
const x = (el: Element | null, attr: string) => Number.parseFloat(el?.getAttribute(attr) ?? "NaN");

describe("CiBar", () => {
  it("CI crossing the threshold: bar spans the −δ line; label names Δ, CI, threshold and status", () => {
    const { container } = render(<CiBar locale="en" row={fail} domain={[-0.22, 0.02]} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      "Δ −0.07, 95 % CI −0.10 to −0.04, threshold −0.05, FAIL",
    );
    const whisker = container.querySelector(".cibar__whisker");
    const line = container.querySelector(".cibar__threshold");
    expect(x(whisker, "x1")).toBeLessThan(x(line, "x1"));
    expect(x(line, "x1")).toBeLessThan(x(whisker, "x2"));
    expect(x(container.querySelector(".cibar__zero"), "x1")).toBeGreaterThan(x(whisker, "x2"));
    expect(container).toHaveTextContent("−0.07 (−0.10, −0.04)");
    expect(container).toHaveTextContent("δ 0.05");
    expect(container).toHaveTextContent("MDE 0.06");
  });
  it("de: decimal comma and German label words", () => {
    render(<CiBar locale="de" row={fail} domain={[-0.22, 0.02]} />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      "Δ −0,07, 95-%-KI −0,10 bis −0,04, Schwelle −0,05, FAIL",
    );
  });
  it("max_drop null: no dashed line, 'no threshold' in the text and the label", () => {
    const { container } = render(
      <CiBar locale="en" row={{ ...fail, max_drop: null }} domain={[-0.2, 0.02]} />,
    );
    expect(container.querySelector(".cibar__threshold")).toBeNull();
    expect(container).toHaveTextContent("no threshold");
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("no threshold, FAIL");
  });
  it("result null: 'n/a' and no whisker", () => {
    const { container } = render(
      <CiBar locale="en" row={decision({ status: "warn", result: null })} domain={[-1, 1]} />,
    );
    expect(container).toHaveTextContent("n/a");
    expect(container.querySelector(".cibar__whisker")).toBeNull();
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("n/a, WARN");
  });
  it("INSUFFICIENT_DATA is greyed, shows n_clusters and no CI", () => {
    const row = decision({ status: "insufficient_data", n_clusters: 22 });
    const { container } = render(<CiBar locale="en" row={row} domain={[-1, 1]} />);
    expect(container.querySelector(".cibar")).toHaveAttribute("data-status", "insufficient_data");
    expect(container).toHaveTextContent("22 clusters < 30");
    expect(container).toHaveTextContent("no CI shown");
    expect(container.querySelector(".cibar__whisker")).toBeNull();
  });
  it("renders no style attribute (ui-spec §7.4) and survives a degenerate domain", () => {
    const { container } = render(<CiBar locale="en" row={fail} domain={[0, 0]} />);
    expect(container.querySelector("[style]")).toBeNull();
    expect(container.innerHTML).not.toContain("NaN");
  });
});
