// Playwright projects of ui-spec §14.2: one static build and one project per fixture set and width (X1.2).
// PR: populated-{360,1280}, empty-{360,1280} (empty basePath, ports 4173/4174). `UI_BASEPATH=1` selects the single
// project populated-basepath-1280 (build `populated-bp` served under /pruefstand/ on 4177, N5.5; `make ui-basepath`).
// Nightly projects (WebKit, mobile) are selected with --project and are added by `UI_EXTENDED=1`.
import { defineConfig, devices } from "@playwright/test";

const SETS = {
  populated: { port: 4173 },
  empty: { port: 4174 },
} as const;
const BASEPATH_PORT = 4177;
const BASE_PATH = "/pruefstand";
const basepathMode = process.env["UI_BASEPATH"] === "1";
const extended = process.env["UI_EXTENDED"] === "1";
const ci = process.env["CI"] !== undefined && process.env["CI"] !== "";

const chromium = (width: number, height: number) => ({
  ...devices["Desktop Chrome"],
  viewport: { width, height },
  locale: "de-DE",
  timezoneId: "Europe/Berlin",
  reducedMotion: "reduce" as const,
});

const ignoreFor = (set: "populated" | "empty") => [
  "**/basepath.spec.ts",
  "**/offline-probe.spec.ts",
  `**/*.${set === "populated" ? "empty" : "populated"}.spec.ts`,
];

const prProjects = (["populated", "empty"] as const).flatMap((set) =>
  ([360, 1280] as const).map((width) => ({
    name: `${set}-${width}`,
    testIgnore: ignoreFor(set),
    metadata: { set },
    use: {
      ...chromium(width, width === 360 ? 740 : 900),
      baseURL: `http://localhost:${SETS[set].port}`,
    },
  })),
);

const extendedProjects = (["populated", "empty"] as const).flatMap((set) => [
  {
    name: `${set}-webkit-1280`,
    testIgnore: ignoreFor(set),
    metadata: { set },
    use: {
      ...devices["Desktop Safari"],
      viewport: { width: 1280, height: 900 },
      baseURL: `http://localhost:${SETS[set].port}`,
    },
  },
  {
    name: `${set}-mobile-chromium`,
    testIgnore: ignoreFor(set),
    metadata: { set },
    use: { ...devices["Pixel 7"], baseURL: `http://localhost:${SETS[set].port}` },
  },
  {
    name: `${set}-mobile-webkit`,
    testIgnore: ignoreFor(set),
    metadata: { set },
    use: { ...devices["iPhone 14"], baseURL: `http://localhost:${SETS[set].port}` },
  },
]);

const basepathProject = {
  name: "populated-basepath-1280",
  testMatch: "**/basepath.spec.ts",
  metadata: { set: "populated" },
  use: { ...chromium(1280, 900), baseURL: `http://localhost:${BASEPATH_PORT}${BASE_PATH}/` },
};

const server = (dir: string, port: number) => ({
  command: `node e2e/static-server.mjs ${dir} ${port}`,
  url: `http://localhost:${port}/`,
  reuseExistingServer: !ci,
  timeout: 60_000,
});

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "test-results",
  fullyParallel: true,
  forbidOnly: ci,
  retries: ci ? 1 : 0,
  ...(ci ? { workers: 2 } : {}),
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: { trace: "on-first-retry", screenshot: "only-on-failure" },
  projects: basepathMode
    ? [basepathProject]
    : extended
      ? [...prProjects, ...extendedProjects]
      : prProjects,
  webServer: basepathMode
    ? {
        command: `../../scripts/dashboard/serve_under_base.sh .sets/populated-bp ${BASE_PATH} .sets/_serve-bp ${BASEPATH_PORT}`,
        url: `http://localhost:${BASEPATH_PORT}${BASE_PATH}/de/`,
        reuseExistingServer: !ci,
        timeout: 60_000,
      }
    : [server(".sets/populated", SETS.populated.port), server(".sets/empty", SETS.empty.port)],
});
