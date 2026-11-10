import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChunkCard } from "@/components/ChunkCard";
import { TenantBadge } from "@/components/TenantBadge";

const base = {
  locale: "en",
  rank: 2,
  chunkId: "gii-bgb-626#0",
  caseTenant: "kanzlei_mueller",
} as const;

describe("ChunkCard", () => {
  it("a foreign tenant is a leak: '⚠ LEAK' text and an accessible label", () => {
    const { container } = render(<ChunkCard {...base} chunkTenant="versicherung_nord" />);
    expect(container).toHaveTextContent("⚠ LEAK");
    expect(container).toHaveTextContent("Leak: chunk from tenant versicherung_nord");
    expect(container.querySelector(".chunk")).toHaveAttribute("data-kind", "leak");
  });
  it("shared_public is not a leak", () => {
    const { container } = render(<ChunkCard {...base} chunkTenant="shared_public" />);
    expect(container).not.toHaveTextContent("LEAK");
    expect(container.querySelector(".chunk")).toHaveAttribute("data-kind", "shared");
    expect(screen.getByText("shared_public")).toBeInTheDocument();
  });
  it("the case's own tenant gets the own badge", () => {
    const { container } = render(<ChunkCard {...base} chunkTenant="kanzlei_mueller" />);
    expect(container.querySelector(".chunk")).toHaveAttribute("data-kind", "own");
    expect(container).not.toHaveTextContent("LEAK");
  });
  it("tenant unknown (empty string or undefined): no badge", () => {
    const a = render(<ChunkCard {...base} chunkTenant="" />);
    expect(a.container.querySelector(".tenant-badge")).toBeNull();
    a.unmount();
    const b = render(<ChunkCard {...base} />);
    expect(b.container.querySelector(".tenant-badge")).toBeNull();
    expect(b.container.querySelector(".chunk")).toHaveAttribute("data-kind", "unknown");
  });
  it("shows rank and id and the withheld note, never chunk text (de too)", () => {
    const { container } = render(<ChunkCard {...base} locale="de" chunkTenant="shared_public" />);
    expect(container).toHaveTextContent("#2");
    expect(container).toHaveTextContent("gii-bgb-626#0");
    expect(container).toHaveTextContent("Abschnittstext wird nicht veröffentlicht");
  });
});

describe("TenantBadge", () => {
  it("always has text", () => {
    render(<TenantBadge locale="en" tenant="stadtwerke_sued" caseTenant="stadtwerke_sued" />);
    expect(screen.getByText("stadtwerke_sued")).toBeInTheDocument();
  });
});
