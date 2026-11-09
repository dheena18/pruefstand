import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LicencesPage from "@/app/[locale]/licences/page";
import { licences } from "@/lib/site";

describe("licences page", () => {
  it.each(["de", "en"] as const)(
    "lists every source, the ODbL offer, no MEMERAG (%s)",
    async (locale) => {
      const { container } = render(await LicencesPage({ params: Promise.resolve({ locale }) }));
      expect(container.querySelector("h1")).toHaveTextContent(
        locale === "de" ? "Quellen und Lizenzen" : "Sources and licences",
      );
      for (const s of licences.sources) expect(container).toHaveTextContent(s.name);
      expect(container.querySelector(".odbl-offer")).toHaveTextContent("ODbL");
      expect(container).not.toHaveTextContent(/MEMERAG/i);
    },
  );
});
