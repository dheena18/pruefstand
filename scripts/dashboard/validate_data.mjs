// `validate_data.mjs <data dir>`: build-time validation of one dashboard data tree (ui-spec §2.4).
// Exit 1 and one line per finding naming the file and the rule, so invalid data never reaches `next build`.
//   rule 1 schema / schema_version      rule 2 index <-> run dirs       rule 3 gate/slices/report/status pairing
//   rule 4 case shards complete, <= 500 rule 5 run_id equals dir name   rule 6 manifest.json hashes
//   rule 7 shard order (R4)             rule 8 no `_empty` id           rule 9 size cap (200 runs / 20 case runs)
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { check, makeValidators, KINDS } from "../../apps/dashboard/src/lib/validate.mjs";
import { MAX_CASE_RUNS, MAX_INDEX_RUNS, MAX_SHARD_CASES, PLACEHOLDER } from "./limits.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const SCHEMAS = path.resolve(here, "../../schemas");

function loadValidators() {
  const schemas = {};
  for (const stem of Object.values(KINDS)) {
    schemas[stem] = JSON.parse(readFileSync(path.join(SCHEMAS, `${stem}.schema.json`), "utf8"));
  }
  return makeValidators(schemas);
}

const subdirs = (dir) =>
  existsSync(dir) ? readdirSync(dir).filter((n) => statSync(path.join(dir, n)).isDirectory()) : [];

/** Validate the tree at `dir`; returns the findings and the two counts the CLI prints. */
export function validateTree(dir) {
  const validators = loadValidators();
  const errors = [];
  const fail = (file, rule, message) => errors.push(`${file}: rule ${rule}: ${message}`);
  const counts = { index: 0, caseRuns: 0 };

  /** Parse + schema-check one file; returns the data or null (and records the finding). */
  function read(rel, kind) {
    const full = path.join(dir, rel);
    let data;
    try {
      data = JSON.parse(readFileSync(full, "utf8"));
    } catch {
      fail(rel, 1, existsSync(full) ? "not valid JSON" : "file is missing");
      return null;
    }
    const result = check(validators, kind, data);
    if (!result.ok) {
      fail(rel, 1, result.message);
      return null;
    }
    return data;
  }

  const index = read("runs/index.json", "index");
  const labels = read("labels.json", "labels");
  void labels;
  if (index === null) return { errors, counts };
  counts.index = index.runs.length;

  // rule 9 (index size) and the newest-20 set
  if (index.runs.length > MAX_INDEX_RUNS) {
    fail("runs/index.json", 9, `${index.runs.length} entries, at most ${MAX_INDEX_RUNS} allowed`);
  }
  const ordered = [...index.runs].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.run_id < b.run_id ? -1 : 1),
  );
  const published = new Set(ordered.slice(0, MAX_CASE_RUNS).map((r) => r.run_id));

  // rule 8, rule 2
  const ids = new Set(index.runs.map((r) => r.run_id));
  if (ids.size !== index.runs.length) fail("runs/index.json", 2, "a run id is listed twice");
  const dirs = new Set(subdirs(path.join(dir, "runs")));
  for (const id of ids) {
    if (id === PLACEHOLDER) fail("runs/index.json", 8, `run id "${PLACEHOLDER}" is reserved`);
    if (!existsSync(path.join(dir, "runs", id, "run.json"))) {
      fail(`runs/${id}/run.json`, 2, "listed in runs/index.json but the file is missing");
    }
  }
  for (const id of dirs) {
    if (!ids.has(id)) fail(`runs/${id}/`, 2, "run directory is not listed in runs/index.json");
  }

  const caseDirs = new Set(subdirs(path.join(dir, "cases")));
  for (const entry of index.runs) {
    checkRun(entry);
  }
  for (const id of caseDirs) {
    if (!ids.has(id)) fail(`cases/${id}/`, 2, "case directory of a run that is not in the index");
  }

  function checkRun(entry) {
    const id = entry.run_id;
    const run = read(`runs/${id}/run.json`, "run");
    if (run !== null && run.run_id !== id) fail(`runs/${id}/run.json`, 5, `run_id is ${run.run_id}`);
    const hasGate = existsSync(path.join(dir, "runs", id, "gate.json"));
    const hasSlices = existsSync(path.join(dir, "runs", id, "slices.json"));
    const hasReport = existsSync(path.join(dir, "runs", id, "report.html"));
    if (hasGate) {
      const gate = read(`runs/${id}/gate.json`, "gate");
      if (gate !== null && gate.candidate_run_id !== id) {
        fail(`runs/${id}/gate.json`, 5, `candidate_run_id is ${gate.candidate_run_id}`);
      }
    }
    if (hasSlices) {
      const slices = read(`runs/${id}/slices.json`, "slices");
      if (slices !== null && slices.run_id !== id) fail(`runs/${id}/slices.json`, 5, `run_id is ${slices.run_id}`);
    }
    if (hasGate !== hasSlices) {
      fail(`runs/${id}/`, 3, hasGate ? "gate.json without slices.json" : "slices.json without gate.json");
    }
    if ((entry.status === null) === hasGate) {
      fail(`runs/${id}/gate.json`, 3, `index status is ${entry.status} but gate.json ${hasGate ? "exists" : "is missing"}`);
    }
    const caseRun = caseDirs.has(id);
    if (caseRun !== published.has(id)) {
      fail(
        `cases/${id}/`,
        9,
        caseRun
          ? "case shards exist for a run outside the newest " + MAX_CASE_RUNS
          : "case shards are missing for one of the newest " + MAX_CASE_RUNS,
      );
    }
    if (published.has(id) && hasGate !== hasReport) {
      fail(`runs/${id}/report.html`, 3, hasGate ? "gate.json without report.html" : "report.html without gate.json");
    }
    if (!published.has(id) && hasReport) {
      fail(`runs/${id}/report.html`, 3, "report.html of a run outside the newest " + MAX_CASE_RUNS);
    }
    if (caseRun) {
      counts.caseRuns += 1;
      checkShards(id);
    }
  }

  function checkShards(id) {
    const files = readdirSync(path.join(dir, "cases", id)).filter((n) => /^\d+\.json$/.test(n));
    const shards = [];
    for (const name of files) {
      const rel = `cases/${id}/${name}`;
      const doc = read(rel, "cases");
      if (doc === null) continue;
      if (doc.run_id !== id) fail(rel, 5, `run_id is ${doc.run_id}`);
      if (doc.cases.length > MAX_SHARD_CASES) fail(rel, 4, `${doc.cases.length} cases, at most ${MAX_SHARD_CASES}`);
      if (String(doc.shard) !== name.replace(".json", "")) fail(rel, 4, `shard field is ${doc.shard}`);
      for (const c of doc.cases) {
        if (c.case_id === PLACEHOLDER) fail(rel, 8, `case id "${PLACEHOLDER}" is reserved`);
      }
      shards.push(doc);
    }
    shards.sort((a, b) => a.shard - b.shard);
    const n = shards[0]?.n_shards ?? 0;
    if (shards.some((s) => s.n_shards !== n)) fail(`cases/${id}/`, 4, "shards disagree on n_shards");
    for (let i = 0; i < n; i += 1) {
      if (!existsSync(path.join(dir, "cases", id, `${i}.json`))) fail(`cases/${id}/${i}.json`, 4, "shard is missing");
    }
    // rule 7: the concatenation is sorted by (failing desc, case_id asc), so every failing case is in shard 0
    let previous = null;
    for (const shard of shards) {
      for (const c of shard.cases) {
        if (c.failing && shard.shard !== 0) {
          fail(`cases/${id}/${shard.shard}.json`, 7, `failing case ${c.case_id} is outside shard 0`);
        }
        const key = [c.failing ? 0 : 1, c.case_id];
        if (previous !== null && (previous[0] > key[0] || (previous[0] === key[0] && previous[1] >= key[1]))) {
          fail(`cases/${id}/${shard.shard}.json`, 7, `case ${c.case_id} breaks the order (failing first, then case_id)`);
        }
        previous = key;
      }
    }
  }

  // rule 6
  const manifestPath = path.join(dir, "manifest.json");
  if (existsSync(manifestPath)) {
    try {
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
      for (const [rel, sha] of Object.entries(manifest.files ?? {})) {
        const full = path.join(dir, rel);
        const actual = existsSync(full) ? createHash("sha256").update(readFileSync(full)).digest("hex") : null;
        if (actual !== sha) fail(rel, 6, actual === null ? "listed in manifest.json but missing" : "sha256 differs from manifest.json");
      }
    } catch {
      fail("manifest.json", 6, "not valid JSON");
    }
  }
  return { errors, counts };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dir = process.argv[2];
  if (dir === undefined || !existsSync(dir)) {
    console.error("usage: validate_data.mjs <data dir>");
    process.exit(2);
  }
  const { errors, counts } = validateTree(path.resolve(dir));
  if (errors.length > 0) {
    for (const line of errors.slice(0, 50)) console.error(line);
    if (errors.length > 50) console.error(`… and ${errors.length - 50} more`);
    process.exit(1);
  }
  console.log(
    `ok: ${dir}: ${counts.index} index entries (max ${MAX_INDEX_RUNS}); case shards for ${counts.caseRuns} runs (max ${MAX_CASE_RUNS})`,
  );
}
