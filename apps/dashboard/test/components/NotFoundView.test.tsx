import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NotFoundView } from "@/components/NotFoundView";

describe("NotFoundView", () => {
  it("renders the title and a link to the runs list in de", () => {
    render(<NotFoundView locale="de" basePath="" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Seite nicht gefunden");
    expect(screen.getByRole("link", { name: "Zurück zu den Läufen" })).toHaveAttribute(
      "href",
      "/de/",
    );
  });
  it("renders the title and a link to the runs list in en", () => {
    render(<NotFoundView locale="en" basePath="" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Page not found");
    expect(screen.getByRole("link", { name: "Back to runs" })).toHaveAttribute("href", "/en/");
  });
  it("links the docs as a plain <a href> only when basePath is set (UI12-09)", () => {
    const { container } = render(<NotFoundView locale="en" basePath="/pruefstand" />);
    const docs = screen.getByRole("link", { name: "Documentation" });
    expect(docs).toHaveAttribute("href", "/pruefstand/docs/");
    expect(docs.tagName).toBe("A");
    expect(docs).not.toHaveAttribute("data-next-link");
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });
  it("has no docs link without basePath", () => {
    render(<NotFoundView locale="de" basePath="" />);
    expect(screen.queryByRole("link", { name: "Dokumentation" })).toBeNull();
  });
});
