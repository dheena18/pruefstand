import { describe, expect, it } from "vitest";

import {
  formatCost,
  formatDate,
  formatDelta,
  formatDeltaCi,
  formatDuration,
  formatGpuSeconds,
  formatPlain,
  formatTokens,
  formatValue,
  refKey,
  refLabel,
  totalTokens,
} from "@/lib/format";

describe("formatDate (Europe/Berlin)", () => {
  it("formats a winter date", () => {
    expect(formatDate("2026-10-31T13:02:00Z", "de")).toBe("31.10.2026, 14:02 MEZ");
    expect(formatDate("2026-12-01T13:02:00Z", "en")).toBe("2026-12-01 14:02 CET");
  });
  it("formats a summer date", () => {
    expect(formatDate("2026-07-15T12:02:00Z", "de")).toBe("15.07.2026, 14:02 MESZ");
    expect(formatDate("2026-07-15T12:02:00Z", "en")).toBe("2026-07-15 14:02 CEST");
  });
  it("answers an en dash for a bad date", () => {
    expect(formatDate("not a date", "de")).toBe("–");
  });
});

describe("refLabel (ui-spec §2.2)", () => {
  it("prefers the PR number", () => {
    expect(
      refLabel({ pr_number: 42, git_ref: "refs/pull/42/merge", git_sha: "d4e5f6a1b2c3" }),
    ).toBe("pr-42@d4e5f6a");
  });
  it("falls back to the git ref without refs/heads/", () => {
    expect(refLabel({ pr_number: null, git_ref: "refs/heads/main", git_sha: "a1b2c3d4e5" })).toBe(
      "main@a1b2c3d",
    );
  });
  it("is an en dash without data", () => {
    expect(refLabel({})).toBe("–");
  });
});

describe("number formats (ui-spec §10.2)", () => {
  it("metric value: 2 decimals, locale separator", () => {
    expect(formatValue(0.857, "en")).toBe("0.86");
    expect(formatValue(0.857, "de")).toBe("0,86");
    expect(formatValue(null, "en")).toBe("–");
  });
  it("delta: sign always, Unicode minus", () => {
    expect(formatDelta(-0.07, "en")).toBe("−0.07");
    expect(formatDelta(0.014, "en")).toBe("+0.01");
    expect(formatDelta(-0.004, "en")).toBe("+0.00");
    expect(formatDelta(-0.005, "en")).toBe("−0.01");
    expect(formatDelta(-0.014, "de")).toBe("−0,01");
    expect(formatDelta(0, "en")).toBe("+0.00");
    expect(formatDelta(-0.07, "de")).toBe("−0,07");
    expect(formatDelta(null, "de")).toBe("–");
  });
  it("delta with CI", () => {
    expect(formatDeltaCi({ mean_diff: -0.07, ci_low: -0.1, ci_high: -0.04 }, "en")).toBe(
      "−0.07 (−0.10, −0.04)",
    );
    expect(formatDeltaCi({ mean_diff: -0.07, ci_low: -0.1, ci_high: -0.04 }, "de")).toBe(
      "−0,07 (−0,10, −0,04)",
    );
    expect(formatDeltaCi(null, "en")).toBe("–");
  });
  it("delta, max and MDE have no sign", () => {
    expect(formatPlain(0.05, "en")).toBe("0.05");
    expect(formatPlain(null, "en")).toBe("–");
  });
  it("duration Xm Ys", () => {
    expect(formatDuration(732.4)).toBe("12m 12s");
    expect(formatDuration(45)).toBe("0m 45s");
    expect(formatDuration(8940)).toBe("149m 0s");
  });
  it("cost: zero is 0 USD", () => {
    expect(formatCost(0, "en")).toBe("0 USD");
    expect(formatCost(0.18, "en")).toBe("0.18 USD");
    expect(formatCost(0.18, "de")).toBe("0,18 USD");
  });
  it("tokens: M, k, < 1 k", () => {
    expect(formatTokens(4_100_000, "en")).toBe("4.1 M");
    expect(formatTokens(4_100_000, "de")).toBe("4,1 M");
    expect(formatTokens(812_000, "en")).toBe("812 k");
    expect(formatTokens(999_999, "en")).toBe("1.0 M");
    expect(formatTokens(999_400, "en")).toBe("999 k");
    expect(formatTokens(300, "en")).toBe("< 1 k");
    expect(formatTokens(0, "en")).toBe("< 1 k");
  });
  it("GPU seconds", () => {
    expect(formatGpuSeconds(2100.4, "en")).toBe("~2,100 GPU-s");
    expect(formatGpuSeconds(2100.4, "de")).toBe("~2.100 GPU-s");
  });
});

describe("tokens = prompt + completion (one sum on every surface)", () => {
  it("adds both", () => {
    expect(totalTokens({ prompt_tokens: 3_000_000, completion_tokens: 1_100_000 })).toBe(4_100_000);
  });
});

describe("refKey", () => {
  it("is pr-N, else the short ref, else an en dash", () => {
    expect(refKey({ pr_number: 4, git_ref: "refs/pull/4/merge" })).toBe("pr-4");
    expect(refKey({ pr_number: null, git_ref: "refs/heads/main" })).toBe("main");
    expect(refKey({ pr_number: null, git_ref: null })).toBe("–");
  });
});

describe("rounding follows the exact binary value, ties half-even, like Python's format()", () => {
  // Python: f"{0.125:.2f}" == "0.12", "0.38", "0.62", "0.88"; f"{0.005:.2f}" == "0.01"; f"{2.675:.2f}" == "2.67"
  it.each([
    [0.125, "0.12"],
    [0.375, "0.38"],
    [0.625, "0.62"],
    [0.875, "0.88"],
    [0.135, "0.14"], // not a tie in binary (0.13500000000000000888…)
    [0.005, "0.01"], // 0.005000000000000000104…: above the tie, so up (Intl would give 0.00)
    [2.675, "2.67"], // 2.67499999999999982236…: below the tie (Intl would give 2.68)
    [1.005, "1.00"],
  ])("%s → %s", (value, text) => {
    expect(formatValue(value, "en")).toBe(text);
    expect(formatPlain(value, "en")).toBe(text);
    expect(formatDelta(value, "en")).toBe(`+${text}`);
  });
  it("de uses the comma and the same ties", () => {
    expect(formatValue(0.125, "de")).toBe("0,12");
    expect(formatDelta(-0.375, "de")).toBe("−0,38");
  });
});

describe("non-finite numbers and large values", () => {
  it("NaN and ±Infinity render as an en dash, never as text", () => {
    for (const v of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(formatValue(v, "en")).toBe("–");
      expect(formatPlain(v, "de")).toBe("–");
      expect(formatDelta(v, "en")).toBe("–");
    }
  });
  it("values from 1e13 up use plain toFixed and stay finite text", () => {
    expect(formatValue(1e13, "en")).toBe("10,000,000,000,000.00");
    expect(formatValue(1e21, "en")).not.toContain("e");
  });
});
