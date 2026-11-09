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

/** Filter key of a run's ref (runs list `?ref=`): `pr-<n>` or the short git ref, `–` without data. */
export function refKey(run: { pr_number?: number | null; git_ref?: string | null }): string {
  return run.pr_number != null ? `pr-${String(run.pr_number)}` : (shortRef(run.git_ref) ?? "–");
}

function shortRef(ref: string | null | undefined): string | null {
  if (!ref) return null;
  return ref.replace(/^refs\/(heads|tags)\//, "");
}

const DASH = "–";
const LOCALE_TAG = { de: "de-DE", en: "en-US" } as const;

function fixed(value: number, locale: Locale, digits = 2): string {
  return new Intl.NumberFormat(LOCALE_TAG[locale], {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** A metric value: 2 decimals with the locale's separator (ui-spec §10.2); `null` → `–`. */
export function formatValue(value: number | null | undefined, locale: Locale): string {
  return value == null ? DASH : fixed(value, locale).replace("-", "−");
}

/** δ, max and MDE: 2 decimals, no sign; `null` → `–`. */
export function formatPlain(value: number | null | undefined, locale: Locale): string {
  return value == null ? DASH : fixed(Math.abs(value), locale);
}

/** Δ: sign always, Unicode minus, 2 decimals (`−0.07`, `+0.01`); a value that rounds to zero reads `+0.00`. */
export function formatDelta(value: number | null | undefined, locale: Locale): string {
  if (value == null) return DASH;
  const negative = Math.round(value * 100) < 0;
  return `${negative ? "−" : "+"}${fixed(Math.abs(value), locale)}`;
}

/** `Δ (low, high)` from a bootstrap result, e.g. `−0.07 (−0.10, −0.04)`; no result → `–`. */
export function formatDeltaCi(
  result: { mean_diff: number; ci_low: number; ci_high: number } | null | undefined,
  locale: Locale,
): string {
  if (result == null) return DASH;
  const { mean_diff: d, ci_low: lo, ci_high: hi } = result;
  return `${formatDelta(d, locale)} (${formatDelta(lo, locale)}, ${formatDelta(hi, locale)})`;
}

/** Duration as `Xm Ys` (ui-spec §10.2). */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60))}m ${String(total % 60)}s`;
}

/** Cost: `0.18 USD`, zero → `0 USD`. */
export function formatCost(usd: number, locale: Locale): string {
  return usd === 0 ? "0 USD" : `${fixed(usd, locale)} USD`;
}

/** The one token sum on every surface: prompt + completion (ui-spec §10.2). */
export function totalTokens(cost: { prompt_tokens: number; completion_tokens: number }): number {
  return cost.prompt_tokens + cost.completion_tokens;
}

/** Tokens: `4.1 M`, `812 k`, `< 1 k`. */
export function formatTokens(tokens: number, locale: Locale): string {
  if (tokens >= 1_000_000) return `${fixed(tokens / 1_000_000, locale, 1)} M`;
  if (tokens >= 1_000) return `${String(Math.round(tokens / 1_000))} k`;
  return "< 1 k";
}

/** GPU seconds: `~2,100 GPU-s` (de `~2.100 GPU-s`). */
export function formatGpuSeconds(seconds: number, locale: Locale): string {
  return `~${new Intl.NumberFormat(LOCALE_TAG[locale], { maximumFractionDigits: 0 }).format(seconds)} GPU-s`;
}
