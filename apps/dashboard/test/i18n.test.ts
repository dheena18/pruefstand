import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import de from "@/i18n/de.json";
import en from "@/i18n/en.json";
import { format, hasKey, isLocale, otherLocale, t } from "@/lib/i18n";

const DE_ONLY = ["metric.", "cause.", "rule.", "info_reason."];
const deOnly = (key: string) => DE_ONLY.some((p) => key.startsWith(p));
const placeholders = (m: string) => [...m.matchAll(/\{([a-z_]+)\s*[,}]/g)].map((x) => x[1]).sort();

const labels = JSON.parse(
  readFileSync(path.join(__dirname, "../fixtures/populated/labels.json"), "utf8"),
) as {
  metrics: Record<string, string>;
  causes: Record<string, string>;
  hard_fail_rules: Record<string, string>;
  informational_reasons: Record<string, string>;
};

describe("de.json / en.json", () => {
  it("have identical key sets except the four de-only data-label prefixes", () => {
    const deKeys = Object.keys(de).filter((k) => !deOnly(k));
    expect(deKeys.sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(en).filter(deOnly)).toEqual([]);
  });

  it("have identical ICU placeholders per key", () => {
    for (const [key, message] of Object.entries(en)) {
      expect(placeholders((de as Record<string, string>)[key] ?? ""), key).toEqual(
        placeholders(message),
      );
    }
  });
});

describe("label coverage (UI12-15, D273)", () => {
  const deKeys = new Set(Object.keys(de));
  const groups: [string, string, Record<string, string>][] = [
    ["metric.", "metrics", labels.metrics],
    ["cause.", "causes", labels.causes],
    ["info_reason.", "informational_reasons", labels.informational_reasons],
    ["rule.", "hard_fail_rules", labels.hard_fail_rules],
  ];
  it.each(groups)(
    "every %s code of labels.json has a de key and de.json has no stale one",
    (prefix, _n, codes) => {
      for (const code of Object.keys(codes))
        expect(deKeys.has(prefix + code), prefix + code).toBe(true);
      const stale = [...deKeys].filter(
        (k) => k.startsWith(prefix) && !(k.slice(prefix.length) in codes),
      );
      expect(stale).toEqual([]);
    },
  );

  it("gives every hard-fail rule a non-empty en label", () => {
    expect(Object.keys(labels.hard_fail_rules).length).toBeGreaterThan(0);
    for (const [code, label] of Object.entries(labels.hard_fail_rules)) {
      expect(label.trim(), code).not.toBe("");
    }
  });
});

describe("format / t", () => {
  it("fills named placeholders", () => {
    expect(format("{a} von {b}", { a: 1, b: "x" })).toBe("1 von x");
  });
  it("selects plural forms and replaces #", () => {
    const m = "{n, plural, one {# Ergebnis} other {# Ergebnisse}}";
    expect(format(m, { n: 1 }, "de")).toBe("1 Ergebnis");
    expect(format(m, { n: 5 }, "de")).toBe("5 Ergebnisse");
  });
  it("t reads the locale dictionary and returns the key when unknown", () => {
    expect(t("de", "nav.runs")).toBe("Läufe");
    expect(t("en", "nav.runs")).toBe("Runs");
    expect(t("en", "no.such.key")).toBe("no.such.key");
    expect(t("en", "filter.count", { n: 2 })).toBe("2 results");
    expect(hasKey("de", "nav.runs")).toBe(true);
  });
  it("keeps an unknown placeholder visible and tolerates unbalanced braces", () => {
    expect(format("{missing}")).toBe("{missing}");
    expect(format("a { b")).toBe("a { b");
    expect(format("{n, select, a {x}}", { n: 1 })).toContain("select");
  });
  it("locale helpers", () => {
    expect(isLocale("de")).toBe(true);
    expect(isLocale("fr")).toBe(false);
    expect(otherLocale("de")).toBe("en");
  });
});
