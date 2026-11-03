import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";

import {
  defaultDataDir,
  loadCaseShard,
  loadGate,
  loadLabels,
  loadRun,
  loadRunIndex,
  loadSlices,
  parseDocument,
} from "@/lib/data";
import { NotFoundError, UnsupportedSchemaError, ValidationError } from "@/lib/errors";
import { footerInfo } from "@/lib/site";
import { alternatesFor } from "@/lib/paths";

const populated = path.join(__dirname, "../../fixtures/populated");
const temps: string[] = [];
afterAll(() => {
  for (const dir of temps) rmSync(dir, { recursive: true, force: true });
});

/** A copy of the populated set with one run directory (kept small: only what the test touches). */
function copyOfRun(id: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), "dash-data-"));
  temps.push(dir);
  cpSync(path.join(populated, "runs", id), path.join(dir, "runs", id), { recursive: true });
  return dir;
}

describe("data layer on fixtures/populated", () => {
  it("loads the index, a gated run with its slices, shard 0 and the labels with their types", async () => {
    const index = await loadRunIndex(populated);
    expect(index.schema_version).toBe("1");
    expect(index.runs.length).toBeGreaterThan(0);
    const gated = index.runs.find((r) => r.status !== null && r.baseline_run_id !== null);
    expect(gated).toBeDefined();
    const id = gated?.run_id ?? "";
    expect((await loadRun(id, populated)).run_id).toBe(id);
    expect((await loadGate(id, populated)).candidate_run_id).toBe(id);
    expect((await loadSlices(id, populated)).run_id).toBe(id);
    const shard = await loadCaseShard(id, 0, populated);
    expect(shard.shard).toBe(0);
    expect(shard.cases.length).toBeGreaterThan(0);
    expect(Object.keys((await loadLabels(populated)).metrics)).toContain("context_recall");
  });

  it("loads an incomplete run and flags it", async () => {
    const index = await loadRunIndex(populated);
    const partial = index.runs.find((r) => !r.complete);
    expect(partial).toBeDefined();
    const run = await loadRun(partial?.run_id ?? "", populated);
    expect(run.complete).toBe(false);
    expect(partial?.status).toBeNull();
  });

  it("loads the no-baseline gate with no_baseline true and baseline_run_id null", async () => {
    const index = await loadRunIndex(populated);
    const entry = index.runs.find((r) => r.no_baseline);
    expect(entry).toBeDefined();
    expect(entry?.baseline_run_id).toBeNull();
    const gate = await loadGate(entry?.run_id ?? "", populated);
    expect(gate.no_baseline).toBe(true);
    expect(gate.baseline_run_id).toBeNull();
  });

  it("gives footer info from the newest run", async () => {
    const info = await footerInfo(populated);
    expect(info.version).toMatch(/\d/);
    expect(info.exportedAt).toMatch(/^20\d\d-/);
  });
});

describe("errors", () => {
  it("rejects an unknown schema_version with UnsupportedSchemaError naming the file", async () => {
    const id = (await loadRunIndex(populated)).runs[0]?.run_id ?? "";
    const dir = copyOfRun(id);
    const file = path.join(dir, "runs", id, "run.json");
    const doc = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
    writeFileSync(file, JSON.stringify({ ...doc, schema_version: "2" }));
    const error = await loadRun(id, dir).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UnsupportedSchemaError);
    expect((error as UnsupportedSchemaError).file).toBe(`runs/${id}/run.json`);
  });

  it("throws NotFoundError for a missing file and for an unsafe id", async () => {
    await expect(loadGate("20990101T000000-000000", populated)).rejects.toBeInstanceOf(
      NotFoundError,
    );
    await expect(loadRun("../etc", populated)).rejects.toBeInstanceOf(NotFoundError);
    await expect(loadCaseShard("x", -1, populated)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("throws ValidationError for invalid JSON and for a schema violation", () => {
    expect(() => parseDocument("index", "{nope", "runs/index.json")).toThrow(ValidationError);
    expect(() =>
      parseDocument("index", '{"schema_version":"1","runs":"x"}', "runs/index.json"),
    ).toThrow(ValidationError);
    expect(() => parseDocument("index", "null", "runs/index.json")).toThrow(UnsupportedSchemaError);
  });
});

describe("helpers", () => {
  it("defaultDataDir honours DASHBOARD_PUBLIC_DATA", () => {
    process.env["DASHBOARD_PUBLIC_DATA"] = "/somewhere";
    expect(defaultDataDir()).toBe("/somewhere");
    delete process.env["DASHBOARD_PUBLIC_DATA"];
    expect(defaultDataDir()).toMatch(/public[\\/]data$/);
  });
  it("alternatesFor gives both locales", () => {
    expect(alternatesFor("")).toEqual({ languages: { de: "/de/", en: "/en/" } });
    expect(alternatesFor("/runs/x/")).toEqual({
      languages: { de: "/de/runs/x/", en: "/en/runs/x/" },
    });
  });
});
