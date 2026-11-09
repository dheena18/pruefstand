import { formatValue } from "@/lib/format";
import { metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import type { DashboardCase, LabelsDocument } from "@/lib/types";

import type { BaselineState } from "./AnswerPair";

function candidateCell(locale: Locale, c: DashboardCase, metric: string): string {
  const status = c.metric_status[metric];
  if (status === "not_applicable") return t(locale, "case.na");
  if (status === "error") return t(locale, "case.metric_error");
  return formatValue(c.metric_values[metric], locale);
}

/** Per-case metric values: base, candidate, and the candidate's `metric_status` (ok / not applicable / error). */
export function CaseMetrics({
  locale,
  labels,
  value,
  baseline,
}: {
  locale: Locale;
  labels: LabelsDocument;
  value: DashboardCase;
  baseline: BaselineState;
}) {
  const metrics = Object.keys(value.metric_values).sort();
  if (metrics.length === 0) return null;
  const base = baseline.state === "found" ? baseline.value : null;
  return (
    <div className="table-wrap" role="region" aria-label={t(locale, "case.metrics")} tabIndex={0}>
      <table className="data">
        <caption>{t(locale, "case.metrics")}</caption>
        <thead>
          <tr>
            <th scope="col">{t(locale, "col.metric")}</th>
            <th scope="col" className="num">
              {t(locale, "col.base")}
            </th>
            <th scope="col" className="num">
              {t(locale, "col.pr")}
            </th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m}>
              <th scope="row">{metricLabel(locale, labels, m)}</th>
              <td className="num">
                {base === null ? "–" : formatValue(base.metric_values[m], locale)}
              </td>
              <td className="num">{candidateCell(locale, value, m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
