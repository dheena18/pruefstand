import { formatDelta, formatPlain, formatValue } from "@/lib/format";
import { metricLabel, reasonLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { MAX_BARS, chartRows, type SectionId } from "@/lib/slices";
import type { DashboardSliceRow, LabelsDocument } from "@/lib/types";

import { ChartShell } from "./ChartShell";
import { SliceChartClient } from "./charts/SliceChart.client";
import { StatusBadge } from "./StatusBadge";

export interface SliceChartProps {
  locale: Locale;
  labels: LabelsDocument;
  /** Rows of the section; the chart takes those of `dimension` × `metric`. */
  rows: DashboardSliceRow[];
  dimension: string;
  metric: string;
  group: SectionId;
}

/** Gated (`gated`, tier-1 `checks`) rows show a status word; informational and reported rows never do. */
export const decides = (group: SectionId): boolean => group === "gated" || group === "checks";

function SliceTable(props: SliceChartProps & { rows: DashboardSliceRow[]; caption: string }) {
  const { locale, labels, rows, caption, group } = props;
  const showStatus = decides(group);
  const head = ["value", "base", "pr", "delta", "threshold", "mde", "clusters"];
  return (
    <div className="table-wrap" role="region" aria-label={caption} tabIndex={0}>
      <table className="data">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {head.map((c) => (
              <th key={c} scope="col" className={c === "value" ? "" : "num"}>
                {t(locale, `col.${c}`)}
              </th>
            ))}
            <th scope="col">{t(locale, showStatus ? "col.status" : "col.reason")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.value} data-status={r.status}>
              <th scope="row" className="mono">
                {r.value}
              </th>
              <td className="num">{formatValue(r.baseline_mean, locale)}</td>
              <td className="num">{formatValue(r.candidate_mean, locale)}</td>
              <td className="num">
                {r.mean_diff == null ? "–" : formatDelta(r.mean_diff, locale)}
              </td>
              <td className="num">{formatPlain(r.max_value ?? r.max_drop, locale)}</td>
              <td className="num">{formatPlain(r.mde, locale)}</td>
              <td className="num">{r.n_clusters ?? "–"}</td>
              <td>
                {showStatus ? (
                  <StatusBadge status={r.status} size="sm" />
                ) : (
                  <>
                    {r.informational_reason == null
                      ? "–"
                      : reasonLabel(locale, labels, r.informational_reason)}
                    {r.notable ? ` ● ${t(locale, "slices.notable")}` : ""}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One chart per (section × dimension × metric) (ui-spec §4.4): at most 12 bars, worst first, with every value in
 * the always-present table. Δ text only where the row has `mean_diff`.
 */
export function SliceChart(props: SliceChartProps) {
  const { locale, labels, rows, dimension, metric, group } = props;
  const sorted = chartRows(rows, dimension, metric);
  const caption = t(locale, "slices.caption", {
    metric: metricLabel(locale, labels, metric),
    dimension,
  });
  return (
    <ChartShell
      locale={locale}
      caption={caption}
      truncatedTo={sorted.length > MAX_BARS ? sorted.length : null}
      chart={
        <SliceChartClient
          locale={locale}
          labels={labels}
          rows={sorted.slice(0, MAX_BARS)}
          showStatus={decides(group)}
        />
      }
      table={<SliceTable {...props} rows={sorted} caption={caption} />}
    />
  );
}
