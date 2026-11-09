import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SiteNotFound from "@/app/not-found";

import { POPULATED } from "../fixtures";

vi.mock("next/navigation", () => ({ useParams: () => ({ locale: "en" }) }));

describe("404 documents", () => {
  it("site 404 (de) has the view, links to the runs list and the footer attribution", async () => {
    process.env["DASHBOARD_PUBLIC_DATA"] = POPULATED;
    const { container } = render(await SiteNotFound());
    expect(container.querySelector("h1")).toHaveTextContent("Seite nicht gefunden");
    expect(container.querySelector("a[href='/de/']")).not.toBeNull();
    expect(container.querySelector("footer")).toHaveTextContent("Fragen abgeleitet aus GermanQuAD");
  });
  it("the locale 404 renders NotFoundView in the route locale", async () => {
    const { default: LocaleNotFound } = await import("@/app/[locale]/not-found");
    const { container } = render(<LocaleNotFound />);
    expect(container.querySelector("h1")).toHaveTextContent("Page not found");
    expect(container.querySelector("a[href='/en/']")).not.toBeNull();
    expect(container.querySelector("a[href$='/docs/']")).toBeNull();
  });
});
