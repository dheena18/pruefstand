import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle, nextMode } from "@/components/ThemeToggle";

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("ThemeToggle", () => {
  it("cycles system -> light -> dark -> system with an aria-label per state", () => {
    render(<ThemeToggle locale="en" />);
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label", "Theme: system");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-label", "Theme: light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-label", "Theme: dark");
    expect(window.localStorage.getItem("pruefstand.theme")).toBe("dark");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-label", "Theme: system");
    expect(document.documentElement).toHaveAttribute("data-theme", "system");
  });
  it("starts from the stored choice and speaks de", () => {
    window.localStorage.setItem("pruefstand.theme", "dark");
    render(<ThemeToggle locale="de" />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Design: dunkel");
  });
  it("still works when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle locale="en" />);
    fireEvent.click(screen.getByRole("button"));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });
  it("nextMode is a 3-cycle", () => {
    expect([nextMode("system"), nextMode("light"), nextMode("dark")]).toEqual([
      "light",
      "dark",
      "system",
    ]);
  });
});
