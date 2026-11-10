import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitationList } from "@/components/CitationList";

describe("CitationList", () => {
  it("renders chips as text with lang=de", () => {
    const { container } = render(
      <CitationList locale="en" citations={["§ 622 Abs. 2 BGB", "Art. 6 DSGVO"]} />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAttribute("lang", "de");
    expect(container).toHaveTextContent("§ 622 Abs. 2 BGB");
  });
  it("empty → no citations text (de)", () => {
    render(<CitationList locale="de" citations={[]} />);
    expect(screen.getByText("keine Zitate")).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });
  it("markup in a citation stays text", () => {
    const { container } = render(<CitationList locale="en" citations={["<b>x</b>"]} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container).toHaveTextContent("<b>x</b>");
  });
});
