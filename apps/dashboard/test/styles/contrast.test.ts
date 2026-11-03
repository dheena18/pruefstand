import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.join(__dirname, "../../src/styles/tokens.css"), "utf8");

function block(selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`);
  expect(start, `${selector} block`).toBeGreaterThanOrEqual(0);
  const end = css.indexOf("}", start);
  const map = new Map<string, string>();
  for (const m of css.slice(start, end).matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    map.set(m[1] ?? "", (m[2] ?? "").trim());
  }
  return map;
}

function channel(value: number): number {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
  );
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const STATUS = ["pass", "warn", "fail", "insufficient", "info"] as const;

// ui-spec §7.1 "tested pairs"
function pairs(): { fg: string; bg: string; min: number }[] {
  const out: { fg: string; bg: string; min: number }[] = [];
  for (const fg of ["text", "text-muted", "accent"]) {
    for (const bg of ["bg", "surface", "surface-2"]) out.push({ fg, bg, min: 4.5 });
  }
  out.push({ fg: "accent-contrast", bg: "accent", min: 4.5 });
  for (const s of STATUS) {
    out.push({ fg: `${s}-fg`, bg: `${s}-bg`, min: 4.5 }, { fg: `${s}-fg`, bg: "bg", min: 4.5 });
  }
  for (const fg of ["border-strong", "focus"]) {
    for (const bg of ["bg", "surface"]) out.push({ fg, bg, min: 3 });
  }
  for (const fg of ["chart-baseline", "chart-candidate", "chart-threshold", "chart-zero"]) {
    out.push({ fg, bg: "bg", min: 3 });
  }
  return out;
}

describe.each([
  ["light", ":root"],
  ["dark", '[data-theme="dark"]'],
])("contrast, %s theme", (_name, selector) => {
  const tokens = block(selector);
  it.each(pairs())("$fg on $bg is at least $min:1", ({ fg, bg, min }) => {
    const front = tokens.get(fg);
    const back = tokens.get(bg);
    expect(front, `--${fg}`).toMatch(/^#[0-9a-f]{6}$/);
    expect(back, `--${bg}`).toMatch(/^#[0-9a-f]{6}$/);
    expect(ratio(front ?? "", back ?? "")).toBeGreaterThanOrEqual(min);
  });
});

describe("system theme", () => {
  it("repeats the dark values under prefers-color-scheme (no attribute / data-theme=system)", () => {
    const media = css.slice(css.indexOf("@media (prefers-color-scheme: dark)"));
    const dark = block('[data-theme="dark"]');
    for (const [name, value] of dark) {
      expect(media, `--${name}`).toContain(`--${name}: ${value};`);
    }
  });
});
