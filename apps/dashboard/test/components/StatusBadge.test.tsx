import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge, badgeFor, type BadgeStatus } from "@/components/StatusBadge";
import { TierBadge } from "@/components/TierBadge";

const WORDS: [BadgeStatus, string][] = [
  ["pass", "PASS"],
  ["warn", "WARN"],
  ["fail", "FAIL"],
  ["insufficient_data", "INSUFFICIENT DATA"],
  ["unsupported_config", "UNSUPPORTED CONFIG"],
  ["NOT_GATED", "NOT GATED"],
  ["NO_BASELINE", "NO BASELINE"],
];

describe("StatusBadge", () => {
  it.each(WORDS)("%s renders icon + text and an accessible name", (status, word) => {
    const { container } = render(<StatusBadge status={status} />);
    expect(screen.getByText(word)).toBeInTheDocument();
    const icon = container.querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveTextContent(word);
  });
  it("uses neutral tokens for NOT GATED and NO BASELINE, never the pass tone", () => {
    const { container } = render(
      <>
        <StatusBadge status="NO_BASELINE" />
        <StatusBadge status="NOT_GATED" />
      </>,
    );
    for (const el of container.querySelectorAll(".badge")) {
      expect(el).toHaveClass("badge--neutral");
      expect(el).not.toHaveClass("badge--pass");
    }
  });
  it("badgeFor: no baseline first, then not gated, else the status", () => {
    expect(badgeFor({ status: "pass", no_baseline: true })).toBe("NO_BASELINE");
    expect(badgeFor({ status: null })).toBe("NOT_GATED");
    expect(badgeFor({ status: "warn" })).toBe("warn");
  });
});

describe("TierBadge", () => {
  it("names the tier in text", () => {
    render(
      <>
        <TierBadge stack="live" locale="en" />
        <TierBadge stack="a40" locale="de" />
      </>,
    );
    expect(screen.getByText("Tier 1")).toBeInTheDocument();
    expect(screen.getByText("Stufe 2")).toBeInTheDocument();
  });
});
