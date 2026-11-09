import { useId } from "react";

import { formatClusters, formatDelta, formatPlain, formatValue } from "@/lib/format";
import { reasonLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import type { DashboardSliceRow, LabelsDocument } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";

export interface SlicePlotProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: DashboardSliceRow[];
  /** Gated rows show their status word; informational rows never do (ui-spec §11.1). */
  showStatus: boolean;
}

const BAR = 8;

/** Bar length in percent of the largest value of the chart (SVG percentages, no `style`, ui-spec §7.4). */
function widths(rows: readonly DashboardSliceRow[]): (v: number) => string {
  const max = Math.max(
    0,
    ...rows.flatMap((r) => [r.baseline_mean, r.candidate_mean, r.max_value ?? 0]),
  );
  return (v) => `${max === 0 ? 0 : Number(((Math.max(v, 0) / max) * 100).toFixed(3))}%`;
}

function RowText({
  row,
  locale,
  labels,
  showStatus,
}: { row: DashboardSliceRow } & Omit<SlicePlotProps, "rows">) {
  const insufficient = row.status === "insufficient_data";
  const threshold =
    row.max_value != null
      ? `${t(locale, "col.max")} ${formatPlain(row.max_value, locale)}`
      : showStatus && row.max_drop != null
        ? `${t(locale, "col.threshold")} ${formatPlain(row.max_drop, locale)}`
        : null;
  return (
    <span className="sliceplot__text">
      {insufficient
        ? t(locale, "slices.insufficient", { clusters: formatClusters(row.n_clusters, locale) })
        : `${formatValue(row.baseline_mean, locale)} → ${formatValue(row.candidate_mean, locale)}`}
      {row.mean_diff == null || insufficient ? null : (
        <span className="sliceplot__delta">{`Δ ${formatDelta(row.mean_diff, locale)}`}</span>
      )}
      {threshold === null ? null : <span className="sliceplot__limit">{threshold}</span>}
      {showStatus ? <StatusBadge status={row.status} size="sm" /> : null}
      {row.notable ? (
        <span className="sliceplot__notable">● {t(locale, "slices.notable")}</span>
      ) : null}
      {row.informational_reason == null ? null : (
        <span className="sliceplot__reason">
          {reasonLabel(locale, labels, row.informational_reason)}
        </span>
      )}
    </span>
  );
}

/**
 * Grouped horizontal bars (ui-spec §4.4, §8): baseline hatched, candidate solid, one pair per value. The caller
 * passes at most 12 rows, worst first. Loaded client-only; the table next to it is the text alternative.
 */
export default function SlicePlot({ locale, labels, rows, showStatus }: SlicePlotProps) {
  const pattern = `hatch-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const width = widths(rows);
  return (
    <ul className="sliceplot">
      {rows.map((row) => {
        const insufficient = row.status === "insufficient_data";
        const label = t(locale, "slices.bar_label", {
          value: row.value,
          base: formatValue(row.baseline_mean, locale),
          cand: formatValue(row.candidate_mean, locale),
        });
        const desc =
          row.status === "insufficient_data"
            ? t(locale, "slices.insufficient", { clusters: formatClusters(row.n_clusters, locale) })
            : `${label}${row.mean_diff == null ? "" : `, Δ ${formatDelta(row.mean_diff, locale)}`}`;
        return (
          <li key={row.value} className="sliceplot__row" data-status={row.status}>
            <span className="sliceplot__value mono">{row.value}</span>
            <svg
              className="sliceplot__svg"
              role="img"
              aria-label={label}
              width="100%"
              height={2 * BAR + 6}
              focusable="false"
            >
              <title>{label}</title>
              <desc>{desc}</desc>
              <defs>
                <pattern
                  id={pattern}
                  width={4}
                  height={4}
                  patternUnits="userSpaceOnUse"
                  patternTransform="rotate(45)"
                >
                  <line className="sliceplot__hatch" x1={0} y1={0} x2={0} y2={4} />
                </pattern>
              </defs>
              <rect
                className={`sliceplot__bar sliceplot__bar--base${insufficient ? " sliceplot__bar--dotted" : ""}`}
                x={0}
                y={2}
                height={BAR}
                width={width(row.baseline_mean)}
                fill={`url(#${pattern})`}
              />
              <rect
                className={`sliceplot__bar sliceplot__bar--cand${insufficient ? " sliceplot__bar--dotted" : ""}`}
                x={0}
                y={BAR + 4}
                height={BAR}
                width={width(row.candidate_mean)}
              />
            </svg>
            <RowText row={row} locale={locale} labels={labels} showStatus={showStatus} />
          </li>
        );
      })}
    </ul>
  );
}
