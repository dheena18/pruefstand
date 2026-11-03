import type { Locale } from "./i18n";

const ZONE = "Europe/Berlin";

/**
 * A date in `Europe/Berlin` (ui-spec §10.1): `de` → `31.10.2026, 14:02 MEZ`, `en` → `2026-10-31 14:02 CET`.
 * Absolute, never relative; the same input always gives the same text.
 */
export function formatDate(iso: string, locale: Locale): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "–";
  if (locale === "de") {
    // `dateStyle` cannot be combined with `timeZoneName` (TypeError), so the fields are spelled out.
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone: ZONE,
      timeZoneName: "short",
    })
      .format(date)
      .replace(" um ", ", ");
  }
  const parts = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: ZONE,
    timeZoneName: "short",
  }).formatToParts(date);
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? "";
  const zone = get("timeZoneName").replace("GMT+1", "CET").replace("GMT+2", "CEST");
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")} ${zone}`;
}

/** Run reference label (ui-spec §2.2): `pr-42@d4e5f6a`, `main@a1b2c3d`, `–`. */
export function refLabel(run: {
  pr_number?: number | null;
  git_ref?: string | null;
  git_sha?: string | null;
}): string {
  const base =
    run.pr_number != null ? `pr-${String(run.pr_number)}` : (shortRef(run.git_ref) ?? "–");
  const sha = run.git_sha ? `@${run.git_sha.slice(0, 7)}` : "";
  return `${base}${sha}`;
}

function shortRef(ref: string | null | undefined): string | null {
  if (!ref) return null;
  return ref.replace(/^refs\/(heads|tags)\//, "");
}
