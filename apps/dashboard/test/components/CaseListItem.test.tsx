import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseListItem } from "@/components/CaseListItem";

import { makeCase } from "../cases-helpers";

const props = {
  locale: "en",
  href: "?case=law-0107",
  pageHref: "/en/runs/r/cases/law-0107/",
} as const;

describe("CaseListItem", () => {
  it("a failing row shows the failing word, the question in its language and a [Page ↗] link", () => {
    const c = makeCase({
      case_id: "law-0107",
      failing: true,
      lang: "en",
      question: "When does it end?",
    });
    const { container } = render(
      <ul>
        <CaseListItem {...props} value={c} selected={false} />
      </ul>,
    );
    expect(container).toHaveTextContent("failing");
    expect(container.querySelector(".case-item__q")).toHaveAttribute("lang", "en");
    expect(container.querySelector(".case-item__q")).toHaveTextContent("When does it end?");
    expect(screen.getByRole("link", { name: /Page/ })).toHaveAttribute(
      "href",
      "/en/runs/r/cases/law-0107/",
    );
    expect(screen.getByRole("link", { name: /law-0107/ })).toHaveAttribute(
      "href",
      "?case=law-0107",
    );
  });
  it("a passing row has no page link; the selected row is aria-current", () => {
    render(
      <ul>
        <CaseListItem {...props} pageHref={null} value={makeCase()} selected />
      </ul>,
    );
    expect(screen.queryByRole("link", { name: /Page/ })).toBeNull();
    expect(screen.getByRole("link", { name: /law-0001/ })).toHaveAttribute("aria-current", "true");
  });
});
