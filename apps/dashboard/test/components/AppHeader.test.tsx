import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppHeader } from "@/components/AppHeader";

vi.mock("next/navigation", () => ({ usePathname: () => "/de/" }));

const props = { locale: "de" as const, githubUrl: "https://example.test/repo" };

describe("AppHeader", () => {
  it("links Runs and Licences, and Try it only when the demo is enabled", () => {
    const { rerender } = render(<AppHeader {...props} demoEnabled={false} />);
    const nav = screen.getAllByRole("navigation", { name: "Hauptnavigation" })[0];
    expect(nav).toBeDefined();
    expect(screen.queryAllByRole("link", { name: "Ausprobieren" })).toHaveLength(0);
    rerender(<AppHeader {...props} demoEnabled />);
    expect(screen.getAllByRole("link", { name: "Ausprobieren" })[0]).toHaveAttribute(
      "href",
      "/de/try/",
    );
    expect(screen.getAllByRole("link", { name: "Läufe" })[0]).toHaveAttribute("href", "/de/");
    expect(screen.getAllByRole("link", { name: "Lizenzen" })[0]).toHaveAttribute(
      "href",
      "/de/licences/",
    );
  });
  it("opens the sheet with aria-expanded, closes on Escape and returns focus to the button", () => {
    render(<AppHeader {...props} demoEnabled={false} />);
    const button = screen.getByRole("button", { name: "Menü" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", "app-sheet");
    expect(document.getElementById("app-sheet")).not.toHaveAttribute("hidden");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(button);
  });
  it("keeps Tab inside the open sheet", () => {
    render(<AppHeader {...props} demoEnabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    const sheet = document.getElementById("app-sheet") as HTMLElement;
    const items = sheet.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(items[0]);
    (items[0] as HTMLElement).focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
