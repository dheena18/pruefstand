// Language rules of ui-spec 9 (WCAG 3.1.1/3.1.2): chrome follows the route locale, data keeps its language.
// On an `en` page the evidence of hard fails, the citations and the chunk ids are still marked `lang="de"`.
import { expect, test } from "@playwright/test";

import { FAIL_CASE, FAIL_RUN } from "./fixture-ids";

test("evidence of a hard fail is lang=de on an en page", async ({ page }) => {
  await page.goto(`/en/runs/${FAIL_RUN}/`);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const evidence = page.locator("q.evidence");
  await expect(evidence.first()).toBeAttached();
  for (const lang of await evidence.evaluateAll((els) => els.map((e) => e.getAttribute("lang")))) {
    expect(lang).toBe("de");
  }
});

test("citations and chunk ids in the case panel are lang=de on an en page", async ({ page }) => {
  await page.goto(`/en/runs/${FAIL_RUN}/cases/?case=${FAIL_CASE}`);
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await expect(page.locator("li.chip").first()).toHaveAttribute("lang", "de");
  const ids = page.locator(".chunk__id");
  await expect(ids.first()).toBeAttached();
  for (const lang of await ids.evaluateAll((els) => els.map((e) => e.getAttribute("lang")))) {
    expect(lang).toBe("de");
  }
});
