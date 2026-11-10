// Per-combination checks shared by the matrix specs (ui-spec §14.2): axe, reflow, lang, footer, CSP.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type Response } from "@playwright/test";

export type Theme = "light" | "dark";
export type Locale = "de" | "en";

declare global {
  interface Window {
    __csp?: string[];
  }
}

/** Sets the theme through the real ThemeToggle storage key and records CSP violations from first paint on. */
export async function prepare(page: Page, theme: Theme): Promise<{ errors: string[] }> {
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem("pruefstand.theme", value);
    } catch {
      // storage blocked: the matrix then runs with the system theme
    }
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      window.__csp?.push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  }, theme);
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" || /content security policy/i.test(msg.text()))
      errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return { errors };
}

export async function csp(
  page: Page,
  response: Response | null,
  errors: string[],
  documentIs404 = false,
): Promise<void> {
  expect(response?.headers()["content-security-policy"], "no CSP response header").toBeUndefined();
  await expect(page.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveCount(1);
  expect(await page.evaluate(() => window.__csp ?? []), "securitypolicyviolation events").toEqual(
    [],
  );
  // The browser logs the 404 status of the document itself as a console error; nothing else is tolerated.
  const own404 = /Failed to load resource: the server responded with a status of 404/;
  expect(documentIs404 ? errors.filter((e) => !own404.test(e)) : errors, "console errors").toEqual(
    [],
  );
}

/** axe-core: 0 serious/critical violations (D139). */
export async function axe(page: Page, disableRules: string[] = []): Promise<void> {
  const result = await new AxeBuilder({ page })
    .disableRules(disableRules)
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map(
      (v) =>
        `${v.id} (${v.impact}): ${v.nodes
          .map((n) => n.target.join(" "))
          .slice(0, 3)
          .join(" | ")}`,
    ),
    "axe serious/critical",
  ).toEqual([]);
}

export async function noHorizontalScroll(page: Page): Promise<void> {
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }));
  expect(widths.scroll, "page-level horizontal scroll").toBeLessThanOrEqual(widths.inner);
}

export async function htmlLang(page: Page, lang: string): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("lang", lang);
}

/** The footer carries the attribution line (with its own `lang`) and the sources link. */
export async function footer(page: Page): Promise<void> {
  const line = page.locator("footer.app-footer p[lang]").first();
  await expect(line).toBeVisible();
  expect(((await line.textContent()) ?? "").length).toBeGreaterThan(20);
  await expect(page.locator('footer.app-footer a[href$="/licences/"]')).toBeVisible();
}
