// Visual regression of the ui-spec §14.2 matrix (nightly, informational until M7; UI9-18). Runs only with UI_VISUAL=1.
// Baselines are written ONLY by `make ui-update-snapshots` inside the pinned Playwright container (fonts and
// rasterisation differ on every other machine), so a missing baseline fails the nightly run instead of passing silently.
import { expect, test } from "@playwright/test";

import { prepare, type Locale, type Theme } from "./checks";
import type { Row, SetName } from "./matrix";
import { rowsOf } from "./matrix-all";

const THEMES: Theme[] = ["light", "dark"];
const LOCALES: Locale[] = ["de", "en"];

test.skip(
  process.env["UI_VISUAL"] !== "1",
  "visual regression runs in the nightly job (UI_VISUAL=1)",
);

const slug = (row: Row) => `${row.page}-${row.state}`.toLowerCase().replace(/[^a-z0-9]+/g, "-");

test("visual matrix", async ({ context }, testInfo) => {
  const set = String(testInfo.project.metadata["set"]) as SetName;
  const failures: string[] = [];
  for (const row of rowsOf(set)) {
    for (const theme of THEMES) {
      for (const locale of row.kind === "report" ? (["de"] as Locale[]) : LOCALES) {
        const page = await context.newPage();
        await prepare(page, theme);
        await page.goto(row.path.replace("{l}", locale));
        if (row.expect.hydrated) await page.locator("main[data-hydrated]").waitFor();
        try {
          await expect(page).toHaveScreenshot(`${slug(row)}-${theme}-${locale}.png`, {
            fullPage: true,
            animations: "disabled",
            caret: "hide",
            maxDiffPixelRatio: 0.01,
            mask: [page.locator("time, .app-footer__meta, td:has(time)")],
          });
        } catch (error) {
          failures.push(`${slug(row)} ${theme} ${locale}: ${String(error).split("\n")[0]}`);
        }
        await page.close();
      }
    }
  }
  expect(failures).toEqual([]);
});
