// basePath smoke (N5.5, UI12-05/06, ui-spec §14.2): the PR matrix builds with an empty basePath, so a hard-coded
// `/data/...` would pass it and break production. This spec runs the `populated-bp` build served under /pruefstand/.
import { expect, test, type Page } from "@playwright/test";

import { FAIL_RUN, MANY_RUN } from "./fixture-ids";

const BASE = "/pruefstand";

/** Collects every same-origin request path and CSP violations; the tests assert on them at the end. */
function watch(page: Page) {
  const paths: string[] = [];
  const violations: string[] = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (
      url.origin ===
      new URL(page.url() === "about:blank" ? "http://localhost:4177" : page.url()).origin
    ) {
      paths.push(url.pathname);
    }
  });
  page.on("console", (msg) => {
    if (/content security policy|refused to/i.test(msg.text())) violations.push(msg.text());
  });
  page.on("pageerror", (err) => violations.push(err.message));
  return { paths, violations };
}

async function cspChecks(page: Page, response: { headers(): Record<string, string> } | null) {
  expect(response?.headers()["content-security-policy"]).toBeUndefined();
  await expect(page.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveCount(1);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("pruefstand.theme", "light"));
});

test("root redirects to de/ and loads theme-init.js under the base path", async ({ page }) => {
  const seen = watch(page);
  await page.goto(`${BASE}/`);
  await page.waitForURL(`**${BASE}/de/`);
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  expect(seen.paths).toContain(`${BASE}/theme-init.js`);
  expect(seen.paths.filter((p) => !p.startsWith(`${BASE}/`))).toEqual([]);
  expect(seen.violations).toEqual([]);
});

test("runs list, FAIL summary and report link stay under the base path", async ({
  page,
  request,
}) => {
  const seen = watch(page);
  const response = await page.goto(`${BASE}/de/`);
  await cspChecks(page, response);
  await expect(page.locator("main[data-hydrated]")).toBeVisible();
  const link = page.locator(`a[href="${BASE}/de/runs/${FAIL_RUN}/"]`).first();
  await expect(link).toBeVisible();
  await link.click();
  await page.waitForURL(`**${BASE}/de/runs/${FAIL_RUN}/`);
  await expect(page.getByText(/FAIL|FEHLGESCHLAGEN/).first()).toBeVisible();
  const report = page.locator("a", { hasText: "HTML-Bericht öffnen" });
  await expect(report).toHaveAttribute("href", `${BASE}/data/runs/${FAIL_RUN}/report.html`);
  const res = await request.get(`${BASE}/data/runs/${FAIL_RUN}/report.html`);
  expect(res.status()).toBe(200);
  expect(await res.text()).toContain('http-equiv="Content-Security-Policy"');
  expect(seen.paths.filter((p) => !p.startsWith(`${BASE}/`))).toEqual([]);
  expect(seen.violations).toEqual([]);
});

test("D-MANY cases list loads shard 1 and a static case page opens", async ({ page }) => {
  const seen = watch(page);
  const response = await page.goto(`${BASE}/de/runs/${MANY_RUN}/cases/`);
  await cspChecks(page, response);
  await expect(page.locator("main[data-hydrated]")).toBeVisible();
  await expect
    .poll(() => seen.paths.filter((p) => p.includes(`/data/cases/${MANY_RUN}/`)).length)
    .toBeGreaterThanOrEqual(1);
  expect(seen.paths).toContain(`${BASE}/data/cases/${MANY_RUN}/0.json`);
  const casePage = page.locator("a.case-item__page").first();
  await expect(casePage).toBeVisible();
  const href = await casePage.getAttribute("href");
  expect(href?.startsWith(`${BASE}/de/runs/${MANY_RUN}/cases/`)).toBe(true);
  await casePage.click();
  await page.waitForURL(`**${href}`);
  await expect(page.locator("h1").first()).toBeVisible();
  expect(seen.paths.filter((p) => !p.startsWith(`${BASE}/`))).toEqual([]);
  expect(seen.violations).toEqual([]);
});

test("unknown path serves the 404 page with status 404 and the /pruefstand/docs/ link", async ({
  page,
}) => {
  const seen = watch(page);
  const response = await page.goto(`${BASE}/de/runs/does-not-exist/`);
  expect(response?.status()).toBe(404);
  await cspChecks(page, response);
  await expect(page.getByRole("heading", { level: 1, name: "Seite nicht gefunden" })).toBeVisible();
  await expect(page.locator("a", { hasText: "Dokumentation" })).toHaveAttribute(
    "href",
    `${BASE}/docs/`,
  );
  expect(seen.paths.filter((p) => !p.startsWith(`${BASE}/`) && p !== "/does-not-exist")).toEqual(
    [],
  );
  expect(seen.violations).toEqual([]);
});
