import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "@/components/EmptyState";
import { ErrorPanel } from "@/components/ErrorPanel";
import { Skeleton } from "@/components/Skeleton";

describe("EmptyState", () => {
  it("renders heading, text and the action link", () => {
    render(
      <EmptyState
        title="Noch keine Läufe exportiert."
        text="Hinweis"
        action={{ href: "/de/", label: "Läufe" }}
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Noch keine Läufe exportiert.",
    );
    expect(screen.getByText("Hinweis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Läufe" })).toHaveAttribute("href", "/de/");
  });
  it("renders without text and action", () => {
    render(<EmptyState title="Leer" />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("ErrorPanel", () => {
  it("is an alert with the error class and a reload button, never a stack trace", () => {
    const reload = vi.fn();
    render(<ErrorPanel locale="en" kind="ValidationError" onReload={reload} />);
    expect(screen.getByRole("alert")).toHaveTextContent("ValidationError");
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledOnce();
  });
});

describe("Skeleton", () => {
  it("is decorative", () => {
    const { container } = render(<Skeleton shape="row" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveClass("skeleton--row");
  });
});
