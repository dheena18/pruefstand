import { readFile } from "node:fs/promises";
import path from "node:path";

import dashboardCases from "../../../../schemas/dashboard_cases.schema.json";
import dashboardRunIndex from "../../../../schemas/dashboard_run_index.schema.json";
import dashboardSlices from "../../../../schemas/dashboard_slices.schema.json";
import gateReport from "../../../../schemas/gate_report.schema.json";
import labels from "../../../../schemas/labels.schema.json";
import runManifest from "../../../../schemas/run_manifest.schema.json";
import type {
  DashboardCases,
  DashboardRunIndex,
  DashboardSlices,
  GateReport,
  LabelsDocument,
  RunManifest,
} from "@/types/generated";

import { NotFoundError, UnsupportedSchemaError, ValidationError } from "./errors";
import { check, makeValidators, type Kind } from "./validate.mjs";

/**
 * Build-time data layer (ui-spec §2.4): every page reads the data tree that `pnpm build` copied to
 * `public/data/` through these functions, so a page can never render unvalidated data. Errors propagate
 * and fail the build; the site has no "bad data" state. Nothing here computes a metric.
 */

const validators = makeValidators({
  run_manifest: runManifest,
  gate_report: gateReport,
  dashboard_run_index: dashboardRunIndex,
  dashboard_slices: dashboardSlices,
  dashboard_cases: dashboardCases,
  labels,
});

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** The directory the build copied the data tree to (`DASHBOARD_PUBLIC_DATA` overrides it for tests). */
export function defaultDataDir(): string {
  return process.env["DASHBOARD_PUBLIC_DATA"] ?? path.join(process.cwd(), "public", "data");
}

/**
 * Validate one parsed JSON text against the schema of `kind`.
 *
 * @throws UnsupportedSchemaError an unknown `schema_version`
 * @throws ValidationError not JSON, or not matching the schema
 */
export function parseDocument<T>(kind: Kind, text: string, file: string): T {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ValidationError(`${file}: not valid JSON`, file);
  }
  const result = check(validators, kind, data);
  if (result.ok) return data as T;
  if (result.unsupported) throw new UnsupportedSchemaError(`${file}: ${result.message}`, file);
  throw new ValidationError(`${file}: ${result.message}`, file);
}

async function load<T>(kind: Kind, relative: string, dir: string): Promise<T> {
  let text: string;
  try {
    text = await readFile(path.join(dir, relative), "utf8");
  } catch {
    throw new NotFoundError(`${relative}: not in the data tree`, relative);
  }
  return parseDocument<T>(kind, text, relative);
}

function safe(id: string, what: string): string {
  if (!SAFE_ID.test(id)) throw new NotFoundError(`${what} ${JSON.stringify(id)} is not an id`, id);
  return id;
}

export async function loadRunIndex(dir: string = defaultDataDir()): Promise<DashboardRunIndex> {
  return load("index", "runs/index.json", dir);
}

export async function loadRun(id: string, dir: string = defaultDataDir()): Promise<RunManifest> {
  return load("run", `runs/${safe(id, "run")}/run.json`, dir);
}

/** The gate report of a run; `NotFoundError` for an ungated run (check `RunIndexEntry.status` first). */
export async function loadGate(id: string, dir: string = defaultDataDir()): Promise<GateReport> {
  return load("gate", `runs/${safe(id, "run")}/gate.json`, dir);
}

export async function loadSlices(
  id: string,
  dir: string = defaultDataDir(),
): Promise<DashboardSlices> {
  return load("slices", `runs/${safe(id, "run")}/slices.json`, dir);
}

/** One case shard; shard 0 holds every failing case. `NotFoundError` for a run without published cases. */
export async function loadCaseShard(
  id: string,
  shard: number,
  dir: string = defaultDataDir(),
): Promise<DashboardCases> {
  if (!Number.isInteger(shard) || shard < 0) {
    throw new NotFoundError(`shard ${String(shard)} is not a shard number`, `cases/${id}`);
  }
  return load("cases", `cases/${safe(id, "run")}/${String(shard)}.json`, dir);
}

export async function loadLabels(dir: string = defaultDataDir()): Promise<LabelsDocument> {
  return load("labels", "labels.json", dir);
}
