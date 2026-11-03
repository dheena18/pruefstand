// B-INVALID-DATA (ui-spec §6): invalid data fails the build and names the file and the rule.
import {
  cpSync,
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeEach, describe, expect, it } from "vitest";

import { node } from "./helpers";

const FIXTURES = path.resolve(__dirname, "../../fixtures");
const populated = path.join(FIXTURES, "populated");
type Entry = { run_id: string; created_at: string; status: string | null };
type Index = { runs: Entry[] };

const readJson = <T>(file: string): T => JSON.parse(readFileSync(file, "utf8")) as T;
const writeJson = (file: string, data: unknown) =>
  writeFileSync(file, JSON.stringify(data, null, 2));

const roots: string[] = [];
afterAll(() => {
  for (const dir of roots) rmSync(dir, { recursive: true, force: true });
});

let dir = "";
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), "dash-validate-"));
  roots.push(dir);
  cpSync(populated, dir, { recursive: true });
});

const index = () => readJson<Index>(path.join(dir, "runs/index.json"));
const newest20 = () =>
  [...index().runs]
    .sort(
      (a, b) =>
        Date.parse(b.created_at) - Date.parse(a.created_at) || (a.run_id < b.run_id ? -1 : 1),
    )
    .slice(0, 20);
const published = () => new Set(newest20().map((r) => r.run_id));
const pruned = () => index().runs.find((r) => !published().has(r.run_id))?.run_id ?? "";
const gatedPublished = () => newest20().find((r) => r.status !== null)?.run_id ?? "";
const multiShard = () =>
  readdirSync(path.join(dir, "cases")).find((id) =>
    existsSync(path.join(dir, "cases", id, "2.json")),
  ) ?? "";

function expectFailure(file: string, rule: number) {
  const { code, out } = node("validate_data.mjs", [dir]);
  expect(code, out).toBe(1);
  expect(out).toContain(file);
  expect(out).toContain(`rule ${String(rule)}`);
}

describe("committed sets", () => {
  it.each(["populated", "empty"])("%s passes and prints both counts", (set) => {
    const { code, out } = node("validate_data.mjs", [path.join(FIXTURES, set)]);
    expect(code, out).toBe(0);
    expect(out).toMatch(/\d+ index entries \(max 200\); case shards for \d+ runs \(max 20\)/);
  });
  it("populated has >= 60 index entries and exactly 20 case-published runs", () => {
    const { out } = node("validate_data.mjs", [populated]);
    const m = /(\d+) index entries .*shards for (\d+) runs/.exec(out);
    expect(Number(m?.[1])).toBeGreaterThanOrEqual(60);
    expect(Number(m?.[2])).toBe(20);
  });
});

describe("B-INVALID-DATA", () => {
  it("(a) a run.json at schema_version 2", () => {
    const id = index().runs[0]?.run_id ?? "";
    const file = path.join(dir, "runs", id, "run.json");
    writeJson(file, { ...readJson<object>(file), schema_version: "2" });
    expectFailure(`runs/${id}/run.json`, 1);
  });
  it("(b) shard 1.json removed from the 3-shard run", () => {
    const id = multiShard();
    expect(id).not.toBe("");
    rmSync(path.join(dir, "cases", id, "1.json"));
    expectFailure(`cases/${id}/1.json`, 4);
  });
  it("(c) report.html removed from a case-published gated run", () => {
    const id = gatedPublished();
    rmSync(path.join(dir, "runs", id, "report.html"));
    expectFailure(`runs/${id}/report.html`, 3);
  });
  it("(d) an index entry without a run directory", () => {
    const id = pruned();
    rmSync(path.join(dir, "runs", id), { recursive: true });
    expectFailure(`runs/${id}/run.json`, 2);
  });
  it("(e) a run directory missing from the index", () => {
    const doc = index();
    const dropped = doc.runs.pop()?.run_id ?? "";
    writeJson(path.join(dir, "runs/index.json"), doc);
    expectFailure(`runs/${dropped}/`, 2);
  });
  it("(f) a shard with 501 cases", () => {
    const id = multiShard();
    const file = path.join(dir, "cases", id, "1.json");
    const doc = readJson<{ cases: { case_id: string; failing: boolean }[] }>(file);
    const base = doc.cases[0] as { case_id: string; failing: boolean };
    while (doc.cases.length < 501)
      doc.cases.push({ ...base, case_id: `zz-${String(doc.cases.length)}`, failing: false });
    writeJson(file, doc);
    expectFailure(`cases/${id}/1.json`, 4);
  });
  it("(g) a manifest hash mismatch", () => {
    const file = path.join(dir, "labels.json");
    writeFileSync(file, `${readFileSync(file, "utf8")}\n`);
    expectFailure("labels.json", 6);
  });
  it("(h) a failing case moved to shard 1", () => {
    const id = multiShard();
    const zero = path.join(dir, "cases", id, "0.json");
    const one = path.join(dir, "cases", id, "1.json");
    const a = readJson<{ cases: { failing: boolean }[] }>(zero);
    const b = readJson<{ cases: unknown[] }>(one);
    const moved = a.cases.shift();
    expect(moved?.failing).toBe(true);
    b.cases.unshift(moved);
    writeJson(zero, a);
    writeJson(one, b);
    expectFailure(`cases/${id}/1.json`, 7);
  });
  it("(i) a run id renamed to _empty", () => {
    const doc = index();
    (doc.runs[0] as Entry).run_id = "_empty";
    writeJson(path.join(dir, "runs/index.json"), doc);
    expectFailure("runs/index.json", 8);
  });
  it("(j) 201 index entries", () => {
    const doc = index();
    while (doc.runs.length < 201) {
      doc.runs.push({
        ...(doc.runs[0] as Entry),
        run_id: `20200101T0000${String(doc.runs.length).padStart(2, "0")}-aaaaaa`,
        created_at: "2020-01-01T00:00:00Z",
      });
    }
    writeJson(path.join(dir, "runs/index.json"), doc);
    expectFailure("runs/index.json", 9);
  });
  it("(k) cases/<id>/ added for a pruned run", () => {
    const id = pruned();
    cpSync(path.join(dir, "cases", multiShard()), path.join(dir, "cases", id), { recursive: true });
    expectFailure(`cases/${id}/`, 9);
  });
  it("(l) cases/<id>/ removed from one of the newest 20", () => {
    const id = [...published()][0] ?? "";
    rmSync(path.join(dir, "cases", id), { recursive: true });
    expectFailure(`cases/${id}/`, 9);
  });
  it("(m) a report.html added to a pruned run", () => {
    const id = pruned();
    cpSync(
      path.join(dir, "runs", gatedPublished(), "report.html"),
      path.join(dir, "runs", id, "report.html"),
    );
    expectFailure(`runs/${id}/report.html`, 3);
  });
  it("gate.json without slices.json, and an index status that disagrees with gate.json", () => {
    const id = gatedPublished();
    renameSync(path.join(dir, "runs", id, "slices.json"), path.join(dir, "runs", id, "slices.bak"));
    expectFailure(`runs/${id}/`, 3);
  });
  it("does not accept a missing argument or directory", () => {
    expect(node("validate_data.mjs", []).code).toBe(2);
    expect(node("validate_data.mjs", [path.join(dir, "nope")]).code).toBe(2);
  });
});
