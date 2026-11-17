// Playwright projects of the Try-it e2e (ui-spec §14.2 "Try-it run", T8.4): one site on 4175 (the script serves
// populated-try, or populated-try-timeout for T-TIMEOUT), the real demo API behind E2E_PORT. Sequential, no
// webServer: scripts/demo/try_e2e.sh starts the site, resets the instance and calls one test at a time.
import { defineConfig, devices } from "@playwright/test";

const chromium = (width: number, height: number) => ({
  ...devices["Desktop Chrome"],
  viewport: { width, height },
  locale: "de-DE",
  timezoneId: "Europe/Berlin",
  reducedMotion: "reduce" as const,
  baseURL: "http://localhost:4175",
});

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/try.spec.ts",
  outputDir: "test-results-try",
  timeout: 240_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [["list"]],
  use: { trace: "off", screenshot: "only-on-failure" },
  projects: [
    { name: "try-360", use: chromium(360, 740) },
    { name: "try-1280", use: chromium(1280, 900) },
  ],
});
