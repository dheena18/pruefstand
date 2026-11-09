import { formatDelta, formatDeltaCi, formatPlain } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import type { SliceDecision } from "@/lib/types";

import { statusWord } from "./StatusBadge";

export interface CiBarProps {
  locale: Locale;
  row: SliceDecision;
  /** Shared x domain of the chart (min, max); every row of one chart uses the same one. */
  domain: [number, number];
}

const HEIGHT = 24;
const MID = HEIGHT / 2;

/** Accessible name of the plot: Δ, CI, threshold and status; `n/a` or the insufficient text without a CI. */
function labelOf(locale: Locale, row: SliceDecision): string {
  const word = statusWord(row.status);
  if (row.status === "insufficient_data") {
    return `${t(locale, "diff.insufficient", { n: row.n_clusters ?? "–" })}, ${word}`;
  }
  const r = row.result;
  if (r === null) return `${t(locale, "diff.na")}, ${word}`;
  return t(locale, "diff.ci_label", {
    delta: formatDelta(r.mean_diff, locale),
    conf: Math.round(r.confidence * 100),
    low: formatDelta(r.ci_low, locale),
    high: formatDelta(r.ci_high, locale),
    threshold:
      row.max_drop == null ? t(locale, "diff.no_threshold") : formatDelta(-row.max_drop, locale),
    status: word,
  });
}

function textOf(locale: Locale, row: SliceDecision): string {
  if (row.status === "insufficient_data") {
    return t(locale, "diff.insufficient", { n: row.n_clusters ?? "–" });
  }
  if (row.result === null) return t(locale, "diff.na");
  const threshold =
    row.max_drop == null
      ? t(locale, "diff.no_threshold")
      : `${t(locale, "col.threshold")} ${formatPlain(row.max_drop, locale)}`;
  return `${formatDeltaCi(row.result, locale)} · ${threshold} · ${t(locale, "col.mde")} ${formatPlain(row.mde, locale)}`;
}

/**
 * One dot-and-whisker row of the Diff chart (ui-spec §4.3): the 0 line, a dashed line at −max_drop (none when the
 * threshold is null), and the CI whisker with the Δ dot. Positions are SVG attributes in percent of the shared
 * domain, never a `style` attribute (§7.4). All numbers come from the exported `result`.
 */
export function CiBar({ locale, row, domain }: CiBarProps) {
  const [lo, hi] = domain;
  const span = hi - lo;
  const x = (v: number): string =>
    `${span === 0 ? 50 : Number((((v - lo) / span) * 100).toFixed(3))}%`;
  const r = row.status === "insufficient_data" ? null : row.result;
  return (
    <div className="cibar" data-status={row.status}>
      <svg
        className="cibar__plot"
        role="img"
        aria-label={labelOf(locale, row)}
        width="100%"
        height={HEIGHT}
        focusable="false"
      >
        <line className="cibar__zero" x1={x(0)} x2={x(0)} y1={0} y2={HEIGHT} />
        {row.max_drop == null ? null : (
          <line
            className="cibar__threshold"
            x1={x(-row.max_drop)}
            x2={x(-row.max_drop)}
            y1={0}
            y2={HEIGHT}
          />
        )}
        {r === null ? null : (
          <>
            <line className="cibar__whisker" x1={x(r.ci_low)} x2={x(r.ci_high)} y1={MID} y2={MID} />
            <line
              className="cibar__cap"
              x1={x(r.ci_low)}
              x2={x(r.ci_low)}
              y1={MID - 5}
              y2={MID + 5}
            />
            <line
              className="cibar__cap"
              x1={x(r.ci_high)}
              x2={x(r.ci_high)}
              y1={MID - 5}
              y2={MID + 5}
            />
            <circle className="cibar__point" cx={x(r.mean_diff)} cy={MID} r={4} />
          </>
        )}
      </svg>
      <span className="cibar__text">{textOf(locale, row)}</span>
    </div>
  );
}
