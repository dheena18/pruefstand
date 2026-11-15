// Runs-list filters (ui-spec §4.1, WCAG 3.2.2 / 4.1.3): state lives in the URL, survives reload and back, a change
// keeps the focus on the control and the live count changes.
import { expect, test } from "@playwright/test";

test("a filter survives reload and back, keeps focus and updates the live count", async ({
  page,
}) => {
  await page.goto("/de/");
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  const count = page.locator(".filter-bar__count");
  await expect(count).toHaveAttribute("aria-live", "polite");
  const before = await count.textContent();
  const status = page.locator("label.filter", { hasText: "Status" }).locator("select");
  await status.focus();
  await status.selectOption("fail");
  await expect(page).toHaveURL(/status=fail/);
  await expect(status).toBeFocused();
  await expect(count).not.toHaveText(before ?? "");
  const filtered = await count.textContent();

  await page.reload();
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await expect(page.locator("label.filter", { hasText: "Status" }).locator("select")).toHaveValue(
    "fail",
  );
  await expect(count).toHaveText(filtered ?? "");

  await page.locator("label.filter", { hasText: "Stufe" }).locator("select").selectOption("1");
  await expect(page).toHaveURL(/tier=1/);
  // filters use router.replace (no history entry): leaving the page and coming back keeps them in the URL
  await page.locator("a.mono:visible").first().click();
  await page.waitForURL(/\/runs\//);
  await page.goBack();
  await expect(page).toHaveURL(/status=fail/);
  await expect(page).toHaveURL(/tier=1/);
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
});

test("the page number is part of the URL", async ({ page }) => {
  await page.goto("/de/?page=2");
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await page.reload();
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator("main")).toContainText("26–50");
});
