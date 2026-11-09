import { formatDelta, formatValue } from "@/lib/format";
import { metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { sliceSuffix } from "@/lib/summary";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

export interface JudgedInfoTableProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: SliceDecision[];
  judgeMode: "github" | "local" | "skipped";
  /** `run.json.judged_cases`. */
  judgedCases: number;
  /** `run.json.judged_subset`: the heading is followed by `summary.judged_subset` (UI13-19). */
  judgedSubset: boolean;
}

const SUBSET_SIZE = 150;

/** Block J (tier 1): judged metrics, informational; replaced by the skipped text when the judge was skipped. */
export function JudgedInfoTable(props: JudgedInfoTableProps) {
  const { locale, labels, rows, judgeMode, judgedCases, judgedSubset } = props;
  if (judgeMode === "skipped") {
    return (
      <section aria-label={t(locale, "info_reason.tier1_judged")} className="judged-skipped">
        <p>{t(locale, "banner.judge_skipped")}</p>
      </section>
    );
  }
  if (rows.length === 0) return null;
  const source = t(locale, `judge_source.${judgeMode}`);
  const heading = t(locale, "summary.judged", { source, n: judgedCases });
  const caption = judgedSubset
    ? `${heading} · ${t(locale, "summary.judged_subset", { n: SUBSET_SIZE })}`
    : heading;
  return (
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
            <th scope="col" className="num">
              {t(locale, "col.judged_cases")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.metric}-${String(i)}`}>
              <th scope="row">
                {metricLabel(locale, labels, row.metric)}
                {sliceSuffix(row) === "" ? null : <span className="mono">{sliceSuffix(row)}</span>}
              </th>
              <td className="num">{formatValue(row.baseline_mean, locale)}</td>
              <td className="num">{formatValue(row.candidate_mean, locale)}</td>
              <td className="num">{formatDelta(row.result?.mean_diff, locale)}</td>
              <td className="num">{judgedCases}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
