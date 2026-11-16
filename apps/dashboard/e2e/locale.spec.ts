// Locale routing (ui-spec §2.2): the root document redirects to /de/, the visible link works, the switch keeps path and
// query, and every localised page declares its hreflang alternates.
import { expect, test } from "@playwright/test";

test("/ redirects to /de/ by meta refresh", async ({ page, request }) => {
  const html = await (await request.get("/")).text();
  expect(html).toContain('http-equiv="refresh"');
  await page.goto("/");
  await page.waitForURL("**/de/");
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
});

test("the visible continue link of the root document leads to /de/", async ({
  browser,
  baseURL,
}) => {
  // JavaScript off and no refresh: the link alone has to work.
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL: baseURL ?? "" });
  const page = await context.newPage();
  const html = await (await page.request.get("/")).text();
  expect(html).toContain('href="de/"');
  expect(html).toContain("Weiter / Continue");
  await context.close();
});

test("the locale switch keeps the path and, after hydration, the query", async ({ page }) => {
  await page.goto("/de/licences/?a=b");
  await expect(page.locator('nav.locale-switch a[hreflang="en"]').first()).toHaveAttribute(
    "href",
    "/en/licences/?a=b",
  );
  await page.goto("/en/licences/");
  await expect(page.locator('nav.locale-switch a[hreflang="de"]').first()).toHaveAttribute(
    "href",
    "/de/licences/",
  );
});

test("localised pages declare hreflang alternates", async ({ page }) => {
  await page.goto("/de/licences/");
  const langs = await page
    .locator('link[rel="alternate"][hreflang]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("hreflang")));
  expect(langs).toEqual(expect.arrayContaining(["de", "en"]));
});
