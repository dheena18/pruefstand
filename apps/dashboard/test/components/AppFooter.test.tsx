import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppFooter } from "@/components/AppFooter";
import licences from "@/content/licences.json";

const info = { version: "0.0.1", exportedAt: "2026-10-31T13:02:00Z" };

describe("AppFooter", () => {
  it("shows the de attribution line from licences.json and links the licences page", () => {
    render(<AppFooter locale="de" licences={licences} info={info} basePath="" />);
    expect(screen.getByRole("contentinfo")).toHaveTextContent(licences.footer_line.de);
    expect(screen.getByRole("link", { name: /Quellen & Lizenzen/ })).toHaveAttribute(
      "href",
      "/de/licences/",
    );
    expect(screen.getByText(/Daten exportiert 31\.10\.2026, 14:02 MEZ/)).toBeInTheDocument();
    expect(
      screen.getByText("Unterstützt die Dokumentation, kein Konformitätsnachweis."),
    ).toBeInTheDocument();
    expect(screen.getByText("pruefstand v0.0.1")).toBeInTheDocument();
  });
  it("shows the en attribution line and prefixes basePath", () => {
    render(<AppFooter locale="en" licences={licences} info={info} basePath="/pruefstand" />);
    expect(screen.getByRole("contentinfo")).toHaveTextContent(licences.footer_line.en);
    expect(screen.getByRole("link", { name: /Sources & licences/ })).toHaveAttribute(
      "href",
      "/pruefstand/en/licences/",
    );
  });
  it("omits version and export time for an empty export", () => {
    render(
      <AppFooter
        locale="en"
        licences={licences}
        info={{ version: null, exportedAt: null }}
        basePath=""
      />,
    );
    expect(screen.queryByText(/data exported/)).toBeNull();
    expect(screen.queryByText(/pruefstand v/)).toBeNull();
  });
});
