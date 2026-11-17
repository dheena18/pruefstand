// The main reading path (ui-spec §4): runs list -> summary -> diff -> slices -> cases -> case page, and back to the
// list with its filters. Real fixture data only.
import { expect, test } from "@playwright/test";

import { FAIL_CASE, FAIL_RUN } from "./fixture-ids";

test("runs list (failing only) -> FAIL summary -> diff -> slices -> cases -> case page, back keeps the filter", async ({
  page,
}) => {
  await page.goto("/de/?status=fail");
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await page.locator(`a[href="/de/runs/${FAIL_RUN}/"]:visible`).first().click();
  await page.waitForURL(`**/de/runs/${FAIL_RUN}/`);
  await expect(page.locator("main").getByText("FAIL", { exact: true }).first()).toBeVisible();
  await expect(page.locator("body")).toContainText("Stufe 1 entscheidet nur über harte Fehler");

  for (const [name, tail] of [
    ["Vergleich", "diff/"],
    ["Slices", "slices/"],
  ] as const) {
    await page.locator(".subnav__item", { hasText: name }).first().click();
    await page.waitForURL(`**/de/runs/${FAIL_RUN}/${tail}`);
    await expect(page.locator("main[data-hydrated]")).toBeAttached();
  }
  await page.locator(".subnav__item", { hasText: "Fälle" }).first().click();
  await page.waitForURL(`**/de/runs/${FAIL_RUN}/cases/`);
  await expect(page.locator("main[data-hydrated]")).toBeAttached();

  await page.goto(`/de/runs/${FAIL_RUN}/cases/${FAIL_CASE}/`);
  await expect(page.locator("body")).toContainText("Kandidaten-Antwort");
  await expect(page.locator("body")).toContainText("Baseline-Antwort");

  await page.goto("/de/?status=fail");
  await page.locator(`a[href="/de/runs/${FAIL_RUN}/"]:visible`).first().click();
  await page.waitForURL(`**/de/runs/${FAIL_RUN}/`);
  await page.goBack();
  await expect(page).toHaveURL(/\/de\/\?status=fail$/);
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await expect(page.locator("main").getByText("FAIL", { exact: true }).first()).toContainText(
    "FAIL",
  );
});

test("the tier-1 summary shows the tier-1 notice and no confidence-interval chart", async ({
  page,
}) => {
  await page.goto(`/de/runs/${FAIL_RUN}/diff/`);
  await expect(page.locator('[data-state="S-TIER1"]').first()).toBeAttached();
  await expect(page.locator("svg.ci-chart, .ci-chart")).toHaveCount(0);
});
