// `derive_fixtures.mjs`: the exported-level fixtures on top of `pruefstand export-dashboard` output (ui-spec §14.1).
// Never hand-written: every file is a copy of a real exported file with new ids and dates.
//   D-BASELINE-MISSING  copy of F-T1 whose gate.json names a baseline run that is not in the index
//   D-MANY              >= 60 runs: one run with 1,500 cases (3 shards, dated newest), clones of F-T1 dated older than
//                       every F-/D- run (so >= 40 of them fall outside the newest 20 = S-CASES-PRUNED), a few with
//                       `block` / `judged_subset` set (workload cells `nightly · b<k>`, `pr · subset`)
//   D-EMPTY             the whole fixtures/empty/ set
// Also writes manifest.json and SOURCE.md. Deterministic: re-running on the same input is byte-identical.
// Usage: node derive_fixtures.mjs [--raw <dir>] [--populated <dir>] [--empty <dir>]
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { MAX_CASE_RUNS, MAX_SHARD_CASES } from "./limits.mjs";
import { emptySourceMd, sourceMd } from "./source_md.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const fixtures = path.join(root, "apps/dashboard/fixtures");
export const TOTAL_RUNS = 62;
export const BIG_CASES = 1500;

/** JSON as Python's `json.dumps(sort_keys=True, indent=2, ensure_ascii=False)` writes it. */
export function dumps(value) {
  const sort = (v) =>
    Array.isArray(v)
      ? v.map(sort)
      : v !== null && typeof v === "object"
        ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort(v[k])]))
        : v;
  return JSON.stringify(sort(value), null, 2) + "\n";
}

const sha6 = (text) => createHash("sha256").update(text).digest("hex").slice(0, 6);
const stamp = (date) => date.toISOString().replace(/[-:]/g, "").slice(0, 15);
export const derivedRunId = (name, date) => `${stamp(date)}-${sha6(name)}`;

const readJson = (file) => JSON.parse(readFileSync(file, "utf8"));
const writeText = (file, text) => {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text);
};

function walkFiles(dir, base = dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walkFiles(full, base) : [path.relative(base, full).split(path.sep).join("/")];
  });
}

export function writeManifest(dir) {
  const files = {};
  for (const rel of walkFiles(dir).sort()) {
    if (rel === "manifest.json" || rel === "SOURCE.md") continue;
    files[rel] = createHash("sha256").update(readFileSync(path.join(dir, rel))).digest("hex");
  }
  writeText(path.join(dir, "manifest.json"), dumps({ schema_version: "1", files }));
}

/** Clone one exported run under `newId`: ids inside the files are rewritten, `edit` may change run/gate. */
function cloneRun(dir, source, newId, createdAt, { withCases, edit = () => {} }) {
  const from = path.join(dir, "runs", source.run_id);
  const to = path.join(dir, "runs", newId);
  const run = readJson(path.join(from, "run.json"));
  run.run_id = newId;
  run.created_at = createdAt.toISOString().replace(".000Z", "Z");
  const entry = { ...source, run_id: newId, created_at: run.created_at };
  const gate = existsSync(path.join(from, "gate.json")) ? readJson(path.join(from, "gate.json")) : null;
  if (gate !== null) gate.candidate_run_id = newId;
  edit({ run, gate, entry });
  writeText(path.join(to, "run.json"), dumps(run));
  if (gate !== null) {
    writeText(path.join(to, "gate.json"), dumps(gate));
    const slices = readJson(path.join(from, "slices.json"));
    slices.run_id = newId;
    writeText(path.join(to, "slices.json"), dumps(slices));
  }
  if (withCases) {
    for (const name of readdirSync(path.join(dir, "cases", source.run_id))) {
      const shard = readJson(path.join(dir, "cases", source.run_id, name));
      shard.run_id = newId;
      writeText(path.join(dir, "cases", newId, name), dumps(shard));
    }
    if (gate !== null) {
      const html = readFileSync(path.join(from, "report.html"), "utf8").split(source.run_id).join(newId);
      writeText(path.join(to, "report.html"), html);
    }
  }
  return { entry, gate, run };
}

/** Rewrite the cases of `source` into `n` cases (3 shards of <= 500), failing cases first (R4). */
function bigCases(dir, source, newId, n) {
  const originals = readdirSync(path.join(dir, "cases", source.run_id))
    .sort()
    .flatMap((name) => readJson(path.join(dir, "cases", source.run_id, name)).cases);
  const cases = [];
  for (let i = 0; cases.length < n; i += 1) {
    for (const c of originals) {
      if (cases.length >= n) break;
      // copies keep every field of the real case; only the answer is cut so a 500-case shard stays under the 1 MB file cap
      const copy = { ...c, case_id: `${c.case_id}-x${String(i).padStart(3, "0")}`, failing: false };
      if (typeof copy.answer === "string" && copy.answer.length > 240) copy.answer = `${copy.answer.slice(0, 239)}…`;
      cases.push(i === 0 ? c : copy);
    }
  }
  cases.sort((a, b) => (a.failing === b.failing ? (a.case_id < b.case_id ? -1 : 1) : a.failing ? -1 : 1));
  const shards = Math.ceil(cases.length / MAX_SHARD_CASES);
  for (let s = 0; s < shards; s += 1) {
    const doc = { schema_version: "1", run_id: newId, shard: s, n_shards: shards, cases: cases.slice(s * MAX_SHARD_CASES, (s + 1) * MAX_SHARD_CASES) };
    writeText(path.join(dir, "cases", newId, `${s}.json`), dumps(doc));
  }
}

export function deriveExported(populated, rawRoles) {
  const indexFile = path.join(populated, "runs/index.json");
  const index = readJson(indexFile);
  const byId = new Map(index.runs.map((r) => [r.run_id, r]));
  const t1 = byId.get(rawRoles["F-T1"]);
  const hard = byId.get(rawRoles["F-HARD-FAIL"]);
  if (t1 === undefined || hard === undefined) throw new Error("F-T1 / F-HARD-FAIL are not in the exported index");
  const entries = [...index.runs];
  const newest = Math.max(...entries.map((r) => Date.parse(r.created_at)));
  const oldest = Math.min(...entries.map((r) => Date.parse(r.created_at)));

  // D-BASELINE-MISSING: baseline_run_id names a run that is not in the index
  const missingDate = new Date(newest + 60_000);
  const missingId = derivedRunId("D-BASELINE-MISSING", missingDate);
  const ghost = derivedRunId("D-BASELINE-MISSING/baseline", new Date(oldest - 86_400_000));
  const done = cloneRun(populated, t1, missingId, missingDate, {
    withCases: true,
    edit: ({ gate, entry }) => {
      gate.baseline_run_id = ghost;
      entry.baseline_run_id = ghost;
    },
  });
  entries.push(done.entry);
  // the report names the (old) baseline id; point it at the ghost too
  const reportFile = path.join(populated, "runs", missingId, "report.html");
  if (t1.baseline_run_id) writeText(reportFile, readFileSync(reportFile, "utf8").split(t1.baseline_run_id).join(ghost));

  // D-MANY: the 1,500-case run is dated newest; clones are older than every other fixture run
  const bigDate = new Date(newest + 120_000);
  const bigId = derivedRunId("D-MANY/1500", bigDate);
  const big = cloneRun(populated, hard, bigId, bigDate, { withCases: true, edit: ({ run, entry }) => { run.n_cases = BIG_CASES; entry.n_cases = BIG_CASES; } });
  bigCases(populated, hard, bigId, BIG_CASES);
  entries.push(big.entry);

  const fixedRuns = entries.length;
  const clones = Math.max(0, TOTAL_RUNS - fixedRuns);
  const keepCases = Math.max(0, MAX_CASE_RUNS - fixedRuns);
  for (let i = 0; i < clones; i += 1) {
    const date = new Date(oldest - 86_400_000 - i * 3_600_000);
    const id = derivedRunId(`D-MANY/clone-${i}`, date);
    const clone = cloneRun(populated, t1, id, date, {
      withCases: i < keepCases,
      edit: ({ run, entry }) => {
        if (i % 5 === 1) { run.workload = "nightly"; run.block = i % 3; entry.workload = "nightly"; entry.block = i % 3; }
        if (i % 7 === 2) { run.judged_subset = true; entry.judged_subset = true; }
      },
    });
    entries.push(clone.entry);
  }
  entries.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.run_id < b.run_id ? -1 : 1));
  writeText(indexFile, dumps({ ...index, runs: entries }));
  return { ids: { missing: missingId, big: bigId, ghost }, entries };
}

export function writeEmpty(emptyDir, populated) {
  rmSync(emptyDir, { recursive: true, force: true });
  writeText(path.join(emptyDir, "runs/index.json"), dumps({ schema_version: "1", runs: [] }));
  cpSync(path.join(populated, "labels.json"), path.join(emptyDir, "labels.json"));
  writeManifest(emptyDir);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const arg = (name, fallback) => {
    const at = process.argv.indexOf(name);
    return at < 0 ? fallback : path.resolve(process.argv[at + 1]);
  };
  const raw = arg("--raw", path.join(fixtures, "raw"));
  const populated = arg("--populated", path.join(fixtures, "populated"));
  const empty = arg("--empty", path.join(fixtures, "empty"));
  const roles = readJson(path.join(raw, "roles.json")).roles;
  const result = deriveExported(populated, roles);
  writeEmpty(empty, populated);
  writeManifest(populated);
  const source = sourceMd({ raw, populated, ids: result.ids });
  writeText(path.join(populated, "SOURCE.md"), source);
  writeText(path.join(empty, "SOURCE.md"), emptySourceMd(/Date: (\S+)/.exec(source)?.[1] ?? ""));
  console.log(`derive_fixtures: ${result.entries.length} runs in the populated index; empty set written`);
}
