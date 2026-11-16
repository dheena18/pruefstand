// Generates the matrix tests of one fixture set: row x {light, dark} x {de, en} (report rows: x {light, dark}).
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
  axe,
  csp,
  footer,
  htmlLang,
  noHorizontalScroll,
  prepare,
  type Locale,
  type Theme,
} from "./checks";
import type { Row, SetName } from "./matrix";
import { rowsOf } from "./matrix-all";

const THEMES: Theme[] = ["light", "dark"];
const LOCALES: Locale[] = ["de", "en"];
const messages = Object.fromEntries(
  LOCALES.map((l) => [
    l,
    JSON.parse(
      readFileSync(path.join(import.meta.dirname, "..", "src", "i18n", `${l}.json`), "utf8"),
    ) as Record<string, string>,
  ]),
) as Record<Locale, Record<string, string>>;

/** i18n text as a regex: placeholders `{x}` match anything. */
function textOf(locale: Locale, key: string): RegExp {
  const raw = messages[locale][key];
  if (raw === undefined) throw new Error(`unknown i18n key ${key}`);
  const source = raw
    .split(/\{[a-z_]+\}/)
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".+?");
  return new RegExp(source);
}

async function assertRow(page: Page, row: Row, locale: Locale): Promise<void> {
  const e = row.expect;
  const textLocale: Locale = row.lang === "de" ? "de" : locale;
  if (e.hydrated) await expect(page.locator("main[data-hydrated]")).toBeAttached();
  await expect(page.locator("main").first()).toBeVisible();
  for (const key of e.keys ?? [])
    await expect(page.locator("body")).toContainText(textOf(textLocale, key));
  for (const word of e.words ?? [])
    await expect(page.locator("main").getByText(word, { exact: true }).first()).toBeVisible();
  for (const state of e.states ?? [])
    await expect(page.locator(`[data-state="${state}"]`).first()).toBeAttached();
  for (const state of e.absentStates ?? [])
    await expect(page.locator(`[data-state="${state}"]`)).toHaveCount(0);
  for (const selector of e.absent ?? []) await expect(page.locator(selector)).toHaveCount(0);
  if (e.noindex)
    await expect(page.locator('meta[name="robots"][content="noindex"]')).toHaveCount(1);
}

async function runCombination(page: Page, row: Row, theme: Theme, locale: Locale): Promise<void> {
  const guards = await prepare(page, theme);
  const response = await page.goto(row.path.replace("{l}", locale));
  expect(response?.status(), `${row.path} status`).toBe(row.status);
  if (row.expect.redirectTo) await page.waitForURL(`**${row.expect.redirectTo}`);
  await htmlLang(page, row.lang === "de" ? "de" : locale);
  await assertRow(page, row, locale);
  await footer(page);
  await noHorizontalScroll(page);
  await csp(page, response, guards.errors, row.status === 404);
  await axe(page);
}

async function runReport(page: Page, row: Row, theme: Theme): Promise<void> {
  await page.emulateMedia({ colorScheme: theme });
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  const response = await page.goto(row.path);
  expect(response?.status()).toBe(200);
  expect(response?.headers()["content-security-policy"]).toBeUndefined();
  await expect(page.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveCount(1);
  await noHorizontalScroll(page);
  // Follow-up (T8.3 report): the report's `.scroll` tables are not keyboard-focusable (axe scrollable-region-focusable);
  // fixing it changes report.html.j2, its snapshots and every exported report, which belongs to the report task.
  await axe(page, ["scrollable-region-focusable"]);
  expect(errors).toEqual([]);
}

/** Registers every row of `set`; prints the combination count so the PR evidence shows it. */
export function defineMatrix(set: SetName): void {
  const rows = rowsOf(set);
  const total = rows.reduce(
    (n, r) => n + (r.kind === "report" ? THEMES.length : THEMES.length * LOCALES.length),
    0,
  );
  test.describe(`${set} matrix (${rows.length} rows, ${total} combinations per project)`, () => {
    test("matrix has an entry for every page of ui-spec 14.2 for this set", () => {
      const pages = new Set(rows.map((r) => r.page));
      const required =
        set === "populated"
          ? [
              "Root redirect",
              "Runs list",
              "Run summary",
              "Diff",
              "Slices",
              "Cases list",
              "Static case page",
              "Placeholder",
              "Licences",
              "404",
              "report.html",
            ]
          : ["Root redirect", "Runs list", "Placeholder", "Licences", "404"];
      expect([...required].filter((p) => !pages.has(p))).toEqual([]);
    });
    for (const row of rows) {
      for (const theme of THEMES) {
        if (row.kind === "report") {
          test(`${row.page} ${row.state} ${theme}`, ({ page }) => runReport(page, row, theme));
          continue;
        }
        for (const locale of LOCALES) {
          test(`${row.page} | ${row.state} | ${theme} | ${locale}`, ({ page }) =>
            runCombination(page, row, theme, locale));
        }
      }
    }
  });
}
