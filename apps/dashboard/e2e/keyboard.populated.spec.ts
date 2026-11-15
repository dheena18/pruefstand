// Keyboard operation (ui-spec §9, WCAG 2.1.1, 2.4.1, 2.4.11, 2.5.8): the skip link is the first tab stop and works,
// the theme toggle is operable by Enter and Space, and interactive targets are at least 24 x 24 px.
import { expect, test } from "@playwright/test";

test("the skip link is the first tab stop and moves focus to the content", async ({ page }) => {
  await page.goto("/de/licences/");
  await page.keyboard.press("Tab");
  const skip = page.locator("a.skip-link");
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#content$/);
});

test("the theme toggle works with Enter and Space", async ({ page }) => {
  test.skip(
    (page.viewportSize()?.width ?? 0) < 640,
    "below 640 px the toggle sits in the menu sheet",
  );
  await page.goto("/de/licences/");
  await expect(page.locator("main")).toBeVisible();
  const toggle = page
    .locator("header button[aria-label^='Design']:visible, header button[title]:visible")
    .first();
  const html = page.locator("html");
  const stored = () => page.evaluate(() => window.localStorage.getItem("pruefstand.theme"));
  await expect(html).toHaveAttribute("data-theme", "system");
  await toggle.focus();
  await page.keyboard.press("Enter"); // system -> light
  await expect(html).toHaveAttribute("data-theme", "light");
  expect(await stored()).toBe("light");
  await page.keyboard.press("Space"); // light -> dark
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await stored()).toBe("dark");
  await expect(toggle).toHaveAttribute("aria-label", "Design: dunkel");
  await page.reload(); // the choice is applied before first paint by theme-init.js
  await expect(html).toHaveAttribute("data-theme", "dark");
});

test("visible links and buttons are at least 24 x 24 px or inline text (WCAG 2.5.8)", async ({
  page,
}) => {
  await page.goto("/de/");
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  const small = await page
    .locator("header a, header button, nav a, nav button, select, main button")
    .evaluateAll((els) =>
      els
        .filter((e) => (e as HTMLElement).offsetParent !== null)
        .map((e) => ({
          name: e.textContent?.trim().slice(0, 20) ?? "",
          box: e.getBoundingClientRect(),
        }))
        .filter((e) => e.box.width < 24 || e.box.height < 24)
        .map((e) => `${e.name} ${Math.round(e.box.width)}x${Math.round(e.box.height)}`),
    );
  expect(small).toEqual([]);
});

test("the focused element is never hidden under the sticky header (WCAG 2.4.11)", async ({
  page,
}) => {
  await page.goto("/de/");
  await expect(page.locator("main[data-hydrated]")).toBeAttached();
  const headerBottom = await page
    .locator("header")
    .first()
    .evaluate((e) => e.getBoundingClientRect().bottom);
  for (let i = 0; i < 25; i += 1) await page.keyboard.press("Tab");
  const top = await page.evaluate(() => document.activeElement?.getBoundingClientRect().top ?? 0);
  expect(top).toBeGreaterThanOrEqual(headerBottom - 1);
});
