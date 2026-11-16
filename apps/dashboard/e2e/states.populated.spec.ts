// C-LOADING and C-SHARD-ERROR (ui-spec §14.2, UI11-18) on the real D-MANY 1,500-case run. No mocks: the real shard
// responses are only delayed (e2e/delay.ts); the error is produced by the mechanism recorded in decisions.md.
import { expect, test } from "@playwright/test";

import { delayRequests } from "./delay";
import { MANY_RUN } from "./fixture-ids";

const LATER_SHARDS = new RegExp(`/data/cases/${MANY_RUN}/[12]\\.json$`);
const LOADING = '[data-state="C-LOADING"]';
const SHARD_ERROR = '[data-state="C-SHARD-ERROR"]';

test("C-LOADING: shards 1+ are held, the status announces progress, then clears", async ({
  page,
}) => {
  const delay = await delayRequests(page, LATER_SHARDS);
  await page.goto(`/de/runs/${MANY_RUN}/cases/`);
  await expect.poll(() => delay.held()).toBe(2);
  const status = page.locator(LOADING);
  await expect(status).toHaveText("Fälle werden geladen: 1 von 3 Teilen");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(page.locator("main")).toContainText(/Fälle \(500\)/);
  delay.release();
  await expect(status).toHaveCount(0);
  await expect(page.locator("main")).toContainText(/Fälle \(1500\)/);
});

test("C-SHARD-ERROR: a failed shard shows the inline alert and Retry loads it", async ({
  page,
  context,
}) => {
  const delay = await delayRequests(page, LATER_SHARDS);
  await page.goto(`/de/runs/${MANY_RUN}/cases/`);
  await expect.poll(() => delay.held()).toBe(2);
  await context.setOffline(true);
  delay.release();
  await expect(page.locator(SHARD_ERROR).first()).toBeVisible();
  await expect(page.locator(SHARD_ERROR).first()).toHaveAttribute("role", "alert");
  await context.setOffline(false);
  const retry = page.getByRole("button", { name: "Erneut versuchen" });
  // Retry loads one failed part (or both); a button that is gone when the next click is due means it is done.
  for (let i = 0; i < 2; i += 1) {
    await retry
      .first()
      .click({ timeout: 3000 })
      .catch(() => undefined);
  }
  await expect(page.locator(SHARD_ERROR)).toHaveCount(0);
  await expect(page.locator("main")).toContainText(/Fälle \(1500\)/);
});
