import { describe, expect, it } from "vitest";

import { formatDate, refLabel } from "@/lib/format";

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
