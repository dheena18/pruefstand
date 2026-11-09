import { formatDelta, formatValue } from "@/lib/format";
import { isKnown, metricLabel, reasonLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { reasonCode } from "@/lib/tables";
import { sliceSuffix } from "@/lib/summary";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

export interface InformationalTableProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: SliceDecision[];
  /** Text placed before the table (tier 2: `summary.judged_subset`, UI13-19). */
  note?: string | undefined;
}

/** Block I: Metric · Base · PR · Δ · Reason. Informational pairs never show a status word (§11.1). */
export function InformationalTable({ locale, labels, rows, note }: InformationalTableProps) {
  if (rows.length === 0) return null;
  const caption = t(locale, "summary.informational");
  return (
    <>
      {note === undefined ? null : <p className="judged-subset-note">{note}</p>}
      <div className="table-wrap" role="region" aria-label={caption} tabIndex={0}>
        <table className="data">
          <caption>{caption}</caption>
          <thead>
            <tr>
              <th scope="col">{t(locale, "col.metric")}</th>
              <th scope="col" className="num">
                {t(locale, "col.base")}
              </th>
              <th scope="col" className="num">
                {t(locale, "col.pr")}
              </th>
              <th scope="col" className="num">
                {t(locale, "col.delta")}
              </th>
              <th scope="col">{t(locale, "col.reason")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const code = reasonCode(row);
              const known = isKnown(locale, labels, "info_reason", code);
              return (
                <tr key={`${row.metric}-${row.dimension}-${row.value}-${String(i)}`}>
                  <th scope="row">
                    {metricLabel(locale, labels, row.metric)}
                    {sliceSuffix(row) === "" ? null : (
                      <span className="mono">{sliceSuffix(row)}</span>
                    )}
                  </th>
                  <td className="num">{formatValue(row.baseline_mean, locale)}</td>
                  <td className="num">{formatValue(row.candidate_mean, locale)}</td>
                  <td className="num">{formatDelta(row.result?.mean_diff, locale)}</td>
                  <td className={known ? undefined : "mono"}>
                    {reasonLabel(locale, labels, code)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
