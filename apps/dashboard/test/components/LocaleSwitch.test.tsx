import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleSwitch, LocaleSwitchView, switchedPath } from "@/components/LocaleSwitch";

vi.mock("next/navigation", () => ({ usePathname: () => "/de/runs/abc/cases/" }));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LocaleSwitch", () => {
  it("links the other locale to the same path and keeps the query, with hreflang", () => {
    render(
      <LocaleSwitchView locale="de" pathname="/de/runs/abc/cases/" search="?case=c1&page=2" />,
    );
    const link = screen.getByRole("link", { name: "EN" });
    expect(link).toHaveAttribute("href", "/en/runs/abc/cases/?case=c1&page=2");
    expect(link).toHaveAttribute("hreflang", "en");
    expect(link).toHaveAttribute("lang", "en");
    expect(screen.getByText("DE")).toHaveAttribute("aria-current", "true");
  });
  it("adds the browser query after hydration and writes no storage", () => {
    const set = vi.spyOn(Storage.prototype, "setItem");
    window.history.replaceState({}, "", "/de/runs/abc/cases/?q=x");
    render(<LocaleSwitch locale="de" />);
    expect(screen.getByRole("link", { name: "EN" })).toHaveAttribute(
      "href",
      "/en/runs/abc/cases/?q=x",
    );
    expect(set).not.toHaveBeenCalled();
  });
  it("switchedPath handles the locale root", () => {
    expect(switchedPath("/de/", "en")).toBe("/en/");
    expect(switchedPath("/en", "de")).toBe("/de/");
  });
});
