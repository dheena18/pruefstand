import Link from "next/link";

import { formatClusters, formatDelta } from "@/lib/format";
import { metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { sliceSuffix } from "@/lib/summary";
import type { GateReport, LabelsDocument, SliceDecision } from "@/lib/types";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

interface Common {
  locale: Locale;
  labels: LabelsDocument;
}

/** Block N: one line of notable slice drops (`dimension=value Δ`), notable rows only. */
export function NotableLine({ locale, rows }: { locale: Locale; rows: SliceDecision[] }) {
  const notable = rows.filter((d) => d.notable === true);
  if (notable.length === 0) return null;
  return (
    <p className="summary-line" data-block="N">
      <strong>{t(locale, "summary.notable")}:</strong>{" "}
      {notable
        .map((d) => `${d.dimension}=${d.value} ${formatDelta(d.result?.mean_diff, locale)}`)
        .join(", ")}
    </p>
  );
}

/** `Not applicable: answer_correctness (12 cases)` from `not_applicable_counts`. */
export function NotApplicableLine({ locale, labels, gate }: Common & { gate: GateReport }) {
  const entries = Object.entries(gate.not_applicable_counts ?? {});
  if (entries.length === 0) return null;
  const cases =
    locale === "en" ? t(locale, "runs.col.cases").toLowerCase() : t(locale, "runs.col.cases");
  return (
    <p className="summary-line" data-block="not-applicable">
      <strong>{t(locale, "summary.not_applicable")}:</strong>{" "}
      {entries
        .map(([m, n]) => `${metricLabel(locale, labels, m)} (${String(n)} ${cases})`)
        .join(", ")}
    </p>
  );
}

/** Block G `INSUFFICIENT_DATA` rows: `<metric> · <dimension>=<value> (<n> clusters)`. */
export function InsufficientLine({ locale, labels, rows }: Common & { rows: SliceDecision[] }) {
  if (rows.length === 0) return null;
  const items = rows.map((d) => {
    const n = formatClusters(d.n_clusters, locale);
    return `${metricLabel(locale, labels, d.metric)}${sliceSuffix(d)} (${n})`;
  });
  return (
    <p className="summary-line" data-block="insufficient">
      <strong>{t(locale, "summary.insufficient")}:</strong> {items.join("; ")}
    </p>
  );
}

/** Top failing cases: links to the static case pages, or plain ids on a pruned run (UI13-16). */
export function TopFailing(
  props: Common & { ids: string[]; runId: string; casesPublished: boolean },
) {
  const { locale, ids, runId, casesPublished } = props;
  if (ids.length === 0) return null;
  return (
    <section className="summary-line" data-block="top-failing">
      <h2>{t(locale, "summary.top_failing")}</h2>
      <ul className="inline-list">
        {ids.map((id) => (
          <li key={id}>
            {casesPublished && SAFE_ID.test(id) ? (
              <Link href={`/${locale}/runs/${runId}/cases/${id}/`} className="mono">
                {id}
              </Link>
            ) : (
              <span className="mono">{id}</span>
            )}
          </li>
        ))}
      </ul>
      {casesPublished ? null : <p>{t(locale, "summary.cases_not_published")}</p>}
    </section>
  );
}
