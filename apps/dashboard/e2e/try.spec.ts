// Try-it rows of ui-spec §14.2 against the REAL demo stack (T8.4, Y7.5; run by scripts/demo/try_e2e.sh on the VM).
// One test per row x {light, dark} x {de, en} per project, title `<row> <theme> <locale>` (the script selects a
// single combination with `-g`). The script resets the e2e instance (in-container POST /v1/_test/reset) before each
// combination and restarts it with the group's env; this spec never resets and never calls Docker. The only
// `page.route` user is e2e/delay.ts (delay only). Answers are never mocked.
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { axe, csp, footer, htmlLang, noHorizontalScroll, prepare, type Locale, type Theme } from "./checks";
import { delayRequests } from "./delay";
import { textOf } from "./i18n-text";

const THEMES: Theme[] = ["light", "dark"];
const LOCALES: Locale[] = ["de", "en"];
const API = `http://127.0.0.1:${process.env["E2E_PORT"] ?? "8091"}`;
const content = JSON.parse(
  readFileSync(path.join(import.meta.dirname, "..", "src", "content", "try.json"), "utf8"),
) as {
  examples: { tenant: string; question: string }[];
  refusal_example: { tenant: string; question: string };
};
const QUESTION = "Welche Kündigungsfrist gilt nach zwei Jahren?";
const TENANT = "kanzlei_mueller";
const GENERATION_MS = 120_000;

/** A console error the row is expected to produce: the browser logs every non-2xx fetch and every refused connection. */
const FETCH_NOISE = /Failed to load resource|net::ERR_/;

interface Ctx {
  page: Page;
  request: APIRequestContext;
  locale: Locale;
  errors: string[];
  firstStatus: () => number | null;
}

type Body = (ctx: Ctx) => Promise<void>;

interface Row {
  id: string;
  /** The page-side request is expected to be answered with an error (console noise allowed). */
  failing?: boolean;
  body: Body;
}

const state = (page: Page, id: string) => page.locator(`[data-state="${id}"]`);
const ask = (page: Page) => page.locator("form.try-form button[type=submit]");
const type = async (page: Page, question: string, tenant = TENANT) => {
  await page.locator(`input[name=tenant][value=${tenant}]`).check();
  await page.locator("#try-question").fill(question);
};

/** One real generation from the test side (same client key as the page); returns when the server answered. */
const preRequest = (request: APIRequestContext) =>
  request.post(`${API}/v1/query`, { data: { tenant_id: TENANT, question: QUESTION }, timeout: GENERATION_MS });

let background: Promise<unknown> | null = null;

const ROWS: Row[] = [
  {
    id: "T-IDLE",
    body: async ({ page, locale }) => {
      await expect(state(page, "T-IDLE")).toBeAttached();
      await expect(ask(page)).toBeDisabled();
      await expect(page.locator(".panel--error")).toHaveCount(0);
      await expect(page.locator("body")).toContainText(textOf(locale, "try.intro"));
    },
  },
  {
    id: "T-INVALID",
    body: async ({ page, locale }) => {
      await page.locator("#try-question").fill("x");
      await page.locator("#try-question").fill("");
      await expect(state(page, "T-INVALID")).toBeAttached();
      await expect(page.locator("#try-problem")).toHaveText(textOf(locale, "try.invalid.empty"));
      await expect(page.locator("#try-question")).toHaveAttribute("aria-invalid", "true");
      await expect(ask(page)).toBeDisabled();
    },
  },
  {
    id: "T-LOADING T-SLOW",
    body: async ({ page, locale }) => {
      const hold = await delayRequests(page, "**/v1/query");
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-LOADING")).toBeAttached();
      await expect(ask(page)).toBeDisabled();
      await expect(page.locator("#try-question")).toHaveJSProperty("readOnly", true);
      await expect(page.getByRole("button", { name: textOf(locale, "try.cancel") })).toBeVisible();
      await expect(state(page, "T-SLOW")).toBeAttached({ timeout: 20_000 });
      await expect(page.locator(".try-slow")).toHaveText(textOf(locale, "try.slow"));
      expect(hold.held()).toBe(1);
    },
  },
  {
    id: "T-CANCELLED",
    body: async ({ page, locale }) => {
      const hold = await delayRequests(page, "**/v1/query");
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-LOADING")).toBeAttached();
      await page.getByRole("button", { name: textOf(locale, "try.cancel") }).click();
      await expect(state(page, "T-CANCELLED")).toBeAttached();
      await expect(page.locator("[aria-live=polite]").first()).toHaveText(textOf(locale, "try.cancelled"));
      await expect(ask(page)).toBeEnabled();
      expect(hold.held()).toBeLessThanOrEqual(1);
    },
  },
  {
    id: "T-SUCCESS",
    body: async ({ page }) => {
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-SUCCESS")).toBeAttached({ timeout: GENERATION_MS });
      await expect(page.locator("#try-answer-h")).toBeFocused();
      await expect(page.locator(".try-answer .case-text")).not.toBeEmpty();
      expect(await page.locator(".try-answer .chips li").count()).toBeGreaterThanOrEqual(1);
      expect(await page.locator(".try-chunk").count()).toBeGreaterThanOrEqual(1);
    },
  },
  {
    id: "T-REFUSED",
    body: async ({ page, locale }) => {
      await type(page, content.refusal_example.question, content.refusal_example.tenant);
      await ask(page).click();
      await expect(state(page, "T-REFUSED")).toBeAttached({ timeout: GENERATION_MS });
      await expect(page.locator(".try-answer [data-state=refused]")).toHaveText(textOf(locale, "try.refused"));
    },
  },
  {
    // Built with NEXT_PUBLIC_DEMO_TIMEOUT_S=1 (populated-try-timeout); the request is held so the client abort is certain.
    id: "T-TIMEOUT",
    failing: true,
    body: async ({ page, locale }) => {
      await delayRequests(page, "**/v1/query");
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-TIMEOUT")).toBeAttached({ timeout: 10_000 });
      await expect(page.locator(".panel--error")).toHaveText(textOf(locale, "try.error.timeout"));
      await expect(page.getByRole("button", { name: textOf(locale, "try.retry") })).toBeVisible();
    },
  },
  {
    id: "T-RATE-LIMITED",
    failing: true,
    body: async ({ page, request, locale, firstStatus }) => {
      expect((await preRequest(request)).status()).toBe(200);
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-RATE-LIMITED")).toBeAttached({ timeout: 20_000 });
      expect(firstStatus()).toBe(429);
      await expect(page.locator("[data-countdown]")).toBeVisible();
      await expect(page.locator(".panel--error p").first()).toContainText(textOf(locale, "try.error.rate_limited"));
      await expect(ask(page)).toBeDisabled();
    },
  },
  {
    // The background generation holds the only slot; the page submits while it runs. A delay on the page side cannot
    // produce `busy` (UI12-04). afterEach awaits the background request, so the next reset finds the instance idle.
    id: "T-BUSY",
    failing: true,
    body: async ({ page, request, locale, firstStatus }) => {
      await type(page, QUESTION); // the form is ready first: a generation of the 0.5B model lasts only ~1-3 s
      background = preRequest(request);
      await page.waitForTimeout(300); // the server has accepted it (retrieval has started) and holds the only slot
      await ask(page).click();
      await expect(state(page, "T-BUSY")).toBeAttached({ timeout: 20_000 });
      expect(firstStatus()).toBe(429);
      await expect(page.locator(".panel--error p").first()).toContainText(textOf(locale, "try.error.busy"));
    },
  },
  {
    id: "T-DAILY-LIMIT",
    failing: true,
    body: async ({ page, request, locale, firstStatus }) => {
      expect((await preRequest(request)).status()).toBe(200);
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-DAILY-LIMIT")).toBeAttached({ timeout: 20_000 });
      expect(firstStatus()).toBe(429);
      await expect(page.locator(".panel--error")).toHaveText(textOf(locale, "try.error.daily_limit"));
      await page.locator("#try-question").fill(`${QUESTION} `);
      await expect(ask(page)).toBeDisabled();
    },
  },
  {
    id: "T-BUDGET",
    failing: true,
    body: async ({ page, locale, firstStatus }) => {
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-BUDGET")).toBeAttached({ timeout: 20_000 });
      expect(firstStatus()).toBe(503);
      await expect(page.locator(".panel--error")).toHaveText(textOf(locale, "try.error.budget"));
      await expect(ask(page)).toBeDisabled();
    },
  },
  {
    id: "T-DEMO-OFF",
    failing: true,
    body: async ({ page, locale, firstStatus }) => {
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-DEMO-OFF")).toBeAttached({ timeout: 20_000 });
      expect(firstStatus()).toBe(503);
      await expect(page.locator(".panel--error")).toHaveText(textOf(locale, "try.error.disabled"));
    },
  },
  {
    // The container is stopped by the script: the browser's fetch fails.
    id: "T-NETWORK",
    failing: true,
    body: async ({ page, locale }) => {
      await type(page, QUESTION);
      await ask(page).click();
      await expect(state(page, "T-NETWORK")).toBeAttached({ timeout: 20_000 });
      await expect(page.locator(".panel--error")).toContainText(textOf(locale, "try.error.network"));
      await expect(page.getByRole("button", { name: textOf(locale, "try.retry") })).toBeVisible();
    },
  },
];


test.afterEach(async () => {
  if (background !== null) await background.catch(() => undefined);
  background = null;
});

for (const row of ROWS) {
  for (const theme of THEMES) {
    for (const locale of LOCALES) {
      test(`${row.id} ${theme} ${locale}`, async ({ page, request }) => {
        test.setTimeout(GENERATION_MS * 2);
        const guards = await prepare(page, theme);
        let first: number | null = null;
        page.on("response", (response) => {
          if (response.url().endsWith("/v1/query") && first === null) first = response.status();
        });
        const response = await page.goto(`/${locale}/try/`);
        expect(response?.status()).toBe(200);
        await htmlLang(page, locale);
        await expect(page.locator("main").first()).toBeVisible();
        await row.body({ page, request, locale, errors: guards.errors, firstStatus: () => first });
        await footer(page);
        await noHorizontalScroll(page);
        const errors = row.failing ? guards.errors.filter((e) => !FETCH_NOISE.test(e)) : guards.errors;
        await csp(page, response, errors);
        await axe(page);
      });
    }
  }
}
