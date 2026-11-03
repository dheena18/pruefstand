// `pnpm build` (apps/dashboard): validate -> copy the data tree to public/data -> next build -> csp -> check_csp
// (ui-spec §2.4). DASHBOARD_DATA_DIR is required; invalid data fails here, before any page is produced.
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const app = process.cwd();
const data = process.env["DASHBOARD_DATA_DIR"];
if (data === undefined || data === "") {
  console.error("build: DASHBOARD_DATA_DIR is required (a data tree: fixtures/populated, fixtures/empty, or a dashboard-data checkout)");
  process.exit(2);
}
const dataDir = path.resolve(data);
if (!existsSync(dataDir)) {
  console.error(`build: DASHBOARD_DATA_DIR ${dataDir} does not exist`);
  process.exit(2);
}

function run(label, command, args, env = {}) {
  const result = spawnSync(command, args, { cwd: app, stdio: "inherit", env: { ...process.env, ...env } });
  if (result.status !== 0) {
    console.error(`build: ${label} failed`);
    process.exit(result.status ?? 1);
  }
}

run("validate_data", process.execPath, [path.join(here, "validate_data.mjs"), dataDir]);
rmSync(path.join(app, "public", "data"), { recursive: true, force: true });
cpSync(dataDir, path.join(app, "public", "data"), { recursive: true });
rmSync(path.join(app, ".next"), { recursive: true, force: true });
rmSync(path.join(app, "out"), { recursive: true, force: true });
const next = path.join(app, "node_modules", "next", "dist", "bin", "next");
run("next build", process.execPath, [next, "build"], { NEXT_TELEMETRY_DISABLED: "1" });
run("csp", process.execPath, [path.join(here, "csp.mjs"), path.join(app, "out")]);
run("check_csp", process.execPath, [path.join(here, "check_csp.mjs"), path.join(app, "out")]);
