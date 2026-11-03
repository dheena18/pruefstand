// `check_fixture_states.mjs [populated dir] [empty dir]`: ui-spec §14.1 state coverage (exit 1 on a gap).
// Allow-listed until T8.3: the tier-2 rows. Needs real refused / error / `en` cases (UI9-12, UI9-16).
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { T83_STATES, caseFacts, statesOf } from "./states.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export function check(populated, empty) {
  const problems = [];
  const warnings = [];
  const states = statesOf(populated);
  for (const [state, runs] of Object.entries(states)) {
    if (runs.length === 0) problems.push(`state ${state} has no fixture in ${path.basename(populated)}`);
  }
  const facts = caseFacts(populated);
  for (const [kind, label] of [["refused", "a refused case"], ["en", "a case with lang en"]]) {
    if (facts[kind].length === 0) problems.push(`populated has no ${label}`);
  }
  // Real runs of this snapshot have no target error; the row is allow-listed (warning) until one does (D646).
  if (facts.error.length === 0) warnings.push("populated has no case with an error yet (allow-listed, D646)");
  const emptyIndex = JSON.parse(readFileSync(path.join(empty, "runs/index.json"), "utf8"));
  if (emptyIndex.runs.length !== 0) problems.push("state L-EMPTY: fixtures/empty has runs");
  if (!existsSync(path.join(empty, "labels.json"))) problems.push("fixtures/empty has no labels.json");
  return { problems, warnings, states, facts };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const populated = path.resolve(process.argv[2] ?? path.join(root, "apps/dashboard/fixtures/populated"));
  const empty = path.resolve(process.argv[3] ?? path.join(root, "apps/dashboard/fixtures/empty"));
  const { problems, warnings, states, facts } = check(populated, empty);
  for (const line of warnings) console.warn(`warning: ${line}`);
  if (problems.length > 0) {
    for (const line of problems) console.error(line);
    process.exit(1);
  }
  const covered = Object.entries(states).map(([s, r]) => `${s} (${r.length})`).join(", ");
  console.log(`ok: ${covered}; refused ${facts.refused.length}, error ${facts.error.length}, en ${facts.en.length}`);
  console.log(`allow-listed until T8.3: ${T83_STATES.join(", ")}`);
}
