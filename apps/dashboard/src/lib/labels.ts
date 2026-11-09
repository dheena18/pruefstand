import type { LabelsDocument } from "@/lib/types";

import { hasKey, t, type Locale } from "./i18n";

/**
 * Data labels (ui-spec §10.1, UI-26, D273): `en` comes from `labels.json` (`LabelsDocument`), `de` from the
 * `metric.` / `cause.` / `rule.` / `info_reason.` keys of `de.json`. An unknown code is returned as is, so the
 * caller can show it in mono; it is never hidden.
 */

type Group = "metric" | "cause" | "rule" | "info_reason";
const DOCUMENT_KEY = {
  metric: "metrics",
  cause: "causes",
  rule: "hard_fail_rules",
  info_reason: "informational_reasons",
} as const;

function lookup(locale: Locale, labels: LabelsDocument, group: Group, code: string): string | null {
  if (locale === "de") {
    const key = `${group}.${code}`;
    return hasKey("de", key) ? t("de", key) : null;
  }
  const table: Record<string, string> = labels[DOCUMENT_KEY[group]];
  return table[code] ?? null;
}

export function metricLabel(locale: Locale, labels: LabelsDocument, code: string): string {
  return lookup(locale, labels, "metric", code) ?? code;
}

export function causeLabel(locale: Locale, labels: LabelsDocument, code: string): string {
  return lookup(locale, labels, "cause", code) ?? code;
}

/** Label of an informational reason code; `–` (no reason) stays `–`. */
export function reasonLabel(locale: Locale, labels: LabelsDocument, code: string): string {
  return lookup(locale, labels, "info_reason", code) ?? code;
}

/**
 * Hard-fail rule name. Published findings carry `rule: "hard_fail"` and the specific rule in `metric`
 * (`tenant_leak`), so the rule code is tried first, then the metric; an unknown pair gives the raw rule.
 */
export function ruleLabel(
  locale: Locale,
  labels: LabelsDocument,
  rule: string,
  metric: string,
): string {
  return lookup(locale, labels, "rule", rule) ?? lookup(locale, labels, "rule", metric) ?? rule;
}

/** True when `code` has a label (so a caller can mark unknown codes). */
export function isKnown(
  locale: Locale,
  labels: LabelsDocument,
  group: Group,
  code: string,
): boolean {
  return lookup(locale, labels, group, code) !== null;
}
