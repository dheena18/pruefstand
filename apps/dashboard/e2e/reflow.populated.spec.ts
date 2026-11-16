// Reflow (WCAG 1.4.10) and text spacing (1.4.12): no page-level horizontal scroll at 400 % zoom and with the WCAG
// text-spacing overrides applied; nothing is clipped by them.
import { expect, test } from "@playwright/test";

import { FAIL_RUN } from "./fixture-ids";

const PATHS = ["/de/", `/de/runs/${FAIL_RUN}/`, `/de/runs/${FAIL_RUN}/cases/`];
const SPACING = `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p { margin-bottom: 2em !important; }`;

for (const path of PATHS) {
  test(`${path} has no page-level horizontal scroll at 400 % zoom`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 256 }); // 1280 x 1024 at 400 %
    await page.goto(path);
    await expect(page.locator("main").first()).toBeVisible();
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(widths[0]).toBeLessThanOrEqual(widths[1] ?? 0);
  });

  test(`${path} is not clipped by the WCAG text-spacing overrides`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("main").first()).toBeVisible();
    // constructed stylesheet: `addStyleTag` is refused by the page's own CSP (style-src 'self')
    await page.evaluate((css) => {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    }, SPACING);
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    expect(widths[0]).toBeLessThanOrEqual(widths[1] ?? 0);
    const clipped = await page
      .locator("h1:not(.sr-only), h2, button, .btn, label")
      .evaluateAll((els) =>
        els
          .filter((e) => (e as HTMLElement).offsetParent !== null)
          .filter(
            (e) =>
              e.scrollHeight > e.clientHeight + 1 && getComputedStyle(e).overflowY === "hidden",
          )
          .map((e) => e.textContent?.trim().slice(0, 30) ?? ""),
      );
    expect(clipped).toEqual([]);
  });
}
