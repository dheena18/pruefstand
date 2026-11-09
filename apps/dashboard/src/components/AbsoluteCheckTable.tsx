import { formatValue } from "@/lib/format";
import { metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { sliceSuffix } from "@/lib/summary";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";
import { ThresholdCell } from "./tableCells";

export interface AbsoluteCheckTableProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: SliceDecision[];
  /** `tier2`: block A. `tier1`: block C, preceded by the hard-fail row. */
  variant: "tier1" | "tier2";
  /** Number of hard-fail findings (tier-1 variant only). */
  hardFailCount?: number;
}

/** Metric · Value (`candidate_mean`) · Max (`max_value`) · Status. */
export function AbsoluteCheckTable({
  locale,
  labels,
  rows,
  variant,
  hardFailCount = 0,
}: AbsoluteCheckTableProps) {
  const caption = t(locale, variant === "tier1" ? "tier1.checks" : "summary.absolute");
  return (
    <div className="table-wrap" role="region" aria-label={caption} tabIndex={0}>
      <table className="data">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{t(locale, variant === "tier1" ? "col.check" : "col.metric")}</th>
            <th scope="col" className="num">
              {t(locale, "col.value")}
            </th>
            <th scope="col" className="num">
              {t(locale, "col.max")}
            </th>
            <th scope="col">{t(locale, "col.status")}</th>
          </tr>
        </thead>
        <tbody>
          {variant === "tier1" ? (
            <tr data-row="hard-fails">
              <th scope="row">{t(locale, "tier1.hard_fail_row")}</th>
              <td className="num">{hardFailCount}</td>
              <td className="num">0</td>
              <td>
                <StatusBadge status={hardFailCount === 0 ? "pass" : "fail"} size="sm" />
              </td>
            </tr>
          ) : null}
          {rows.map((row, i) => (
            <tr key={`${row.metric}-${row.dimension}-${row.value}-${String(i)}`}>
              <th scope="row">
                {metricLabel(locale, labels, row.metric)}
                {sliceSuffix(row) === "" ? null : <span className="mono">{sliceSuffix(row)}</span>}
              </th>
              <td className="num">{formatValue(row.candidate_mean, locale)}</td>
              <td className="num">
                <ThresholdCell value={row.max_value} locale={locale} />
              </td>
              <td>
                <StatusBadge status={row.status} size="sm" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
