import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.join(__dirname, "../../../..");
const limits = readFileSync(path.join(root, "scripts/dashboard/limits.mjs"), "utf8");
const python = readFileSync(
  path.join(root, "packages/pruefstand/src/pruefstand/core/models/dashboard.py"),
  "utf8",
);
const js = (name: string) => Number(new RegExp(`${name} = (\\d+)`).exec(limits)?.[1]);
const py = (name: string) => Number(new RegExp(`${name}: Final = (\\d+)`).exec(python)?.[1]);

describe("size caps", () => {
  it.each(["MAX_INDEX_RUNS", "MAX_CASE_RUNS", "MAX_SHARD_CASES"])(
    "%s equals the Python constant in pruefstand.core.models.dashboard (no drift)",
    (name) => {
      expect(js(name)).toBeGreaterThan(0);
      expect(js(name)).toBe(py(name));
    },
  );
});
