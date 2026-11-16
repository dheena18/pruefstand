// Lighthouse CI (T8.3 S6; nightly job `lighthouse`, informational until M7): runs list, a FAIL summary and the cases
// list of the 1,500-case D-MANY run, served from `.sets/populated`. Run ids are read from the fixture index.
const fs = require("node:fs");
const path = require("node:path");

const index = JSON.parse(
    fs.readFileSync(path.join(__dirname, "fixtures/populated/runs/index.json"), "utf8"),
).runs;
const many = index.find((r) => r.n_cases >= 1500).run_id;
const fail = index.find(
    (r) => r.stack === "live" && r.status === "fail" && r.n_cases < 1500,
).run_id;
const base = "http://localhost:4173";

module.exports = {
    ci: {
        collect: {
            startServerCommand: "node e2e/static-server.mjs .sets/populated 4173",
            startServerReadyPattern: "static-server",
            url: [`${base}/de/`, `${base}/de/runs/${fail}/`, `${base}/de/runs/${many}/cases/`],
            numberOfRuns: 1,
            settings: { chromeFlags: "--no-sandbox --headless=new" },
        },
        assert: {
            assertions: {
                "categories:performance": ["warn", { minScore: 0.9 }],
                "categories:accessibility": ["warn", { minScore: 0.95 }],
                "categories:best-practices": ["warn", { minScore: 0.95 }],
                "categories:seo": ["warn", { minScore: 0.9 }],
                "largest-contentful-paint": ["warn", { maxNumericValue: 2500 }],
                "cumulative-layout-shift": ["warn", { maxNumericValue: 0.1 }],
                "resource-summary:script:size": ["warn", { maxNumericValue: 250000 }],
            },
        },
        upload: { target: "filesystem", outputDir: "lighthouse-report" },
    },
};
