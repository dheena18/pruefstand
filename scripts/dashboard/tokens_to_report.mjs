// `pnpm gen:report-tokens`: apps/dashboard/src/styles/tokens.css -> report/templates/_tokens.css (ui-spec §7).
// The report inlines the same values (light, plus dark under prefers-color-scheme). CI regenerates and fails on a diff.
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = path.join(root, "apps/dashboard/src/styles/tokens.css");
const target = path.join(
  root,
  "packages/pruefstand/src/pruefstand/report/templates/_tokens.css",
);

// One output line per group, in this order (the report does not use the chart tokens or the font stacks).
const LIGHT_LINES = [
  ["bg", "surface", "surface-2", "border", "border-strong"],
  ["text", "text-muted", "accent", "accent-contrast", "focus"],
  ["pass-fg", "pass-bg", "warn-fg", "warn-bg"],
  ["fail-fg", "fail-bg", "insufficient-fg", "insufficient-bg"],
  ["info-fg", "info-bg"],
  ["text-xs", "text-sm", "text-base", "text-lg", "text-xl"],
  ["text-2xl", "text-3xl"],
  ["space-1", "space-2", "space-3", "space-4", "space-6", "space-8", "space-12"],
  ["radius-sm", "radius-md", "shadow-1"],
];
const DARK_LINES = [
  ["bg", "surface", "surface-2", "border", "border-strong"],
  ["text", "text-muted", "accent", "accent-contrast", "focus"],
  ["pass-fg", "pass-bg", "warn-fg", "warn-bg"],
  ["fail-fg", "fail-bg", "insufficient-fg", "insufficient-bg"],
  ["info-fg", "info-bg", "shadow-1"],
];

/** `--name: value;` declarations of the first block that starts with `selector`. */
export function declarations(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`tokens.css has no ${selector} block`);
  const end = css.indexOf("}", start);
  const map = new Map();
  for (const m of css.slice(start, end).matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) map.set(m[1], m[2].trim());
  return map;
}

function lines(map, groups) {
  return groups.map((names) =>
    names
      .map((name) => {
        if (!map.has(name)) throw new Error(`tokens.css lacks --${name}`);
        return `--${name}:${map.get(name)};`;
      })
      .join(""),
  );
}

export function render(css) {
  const light = lines(declarations(css, ":root"), LIGHT_LINES);
  const dark = lines(declarations(css, '[data-theme="dark"]'), DARK_LINES);
  return [":root{", ...light, "}", "@media (prefers-color-scheme:dark){:root{", ...dark, "}}", ""].join("\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeFileSync(target, render(readFileSync(source, "utf8")));
  console.log("wrote report/templates/_tokens.css from tokens.css");
}
