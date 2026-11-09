import { formatDelta, formatDeltaCi, formatPlain, formatValue } from "@/lib/format";
import { metricLabel, reasonLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import { reasonCode } from "@/lib/tables";
import { sliceSuffix } from "@/lib/summary";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";
import { ThresholdCell } from "./tableCells";

export interface MetricTableProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: SliceDecision[];
  caption: string;
  /** `gated`: 7 columns with status (block G); `reported`: tier-1 block R without status words. */
  variant: "gated" | "reported";
}

const RANK: Record<string, number> = { fail: 0, warn: 1, pass: 2, insufficient_data: 3 };

/** Gated rows sorted FAIL → WARN → PASS → INSUFFICIENT_DATA (stable within a status). */
export function sortByStatus(rows: SliceDecision[]): SliceDecision[] {
  return [...rows].sort((a, b) => (RANK[a.status] ?? 4) - (RANK[b.status] ?? 4));
}

function Name({
  row,
  locale,
  labels,
}: { row: SliceDecision } & Pick<MetricTableProps, "locale" | "labels">) {
  return (
    <th scope="row">
      {metricLabel(locale, labels, row.metric)}
      {sliceSuffix(row) === "" ? null : <span className="mono">{sliceSuffix(row)}</span>}
    </th>
  );
}

function Header({ locale, variant }: Pick<MetricTableProps, "locale" | "variant">) {
  const cols =
    variant === "gated"
      ? ["metric", "base", "pr", "delta_ci", "threshold", "mde", "status"]
      : ["metric", "base", "pr", "delta", "mde", "max", "reason"];
  return (
    <tr>
      {cols.map((c) => (
        <th key={c} scope="col" className={c === "metric" || c === "reason" ? "" : "num"}>
          {t(locale, `col.${c}`)}
        </th>
      ))}
    </tr>
  );
}

/** Block G (7 columns incl. δ and MDE) or block R (tier 1, reported; no status word). Numbers per §10.2. */
export function MetricTable(props: MetricTableProps) {
  const { locale, labels, rows, caption, variant } = props;
  const ordered = variant === "gated" ? sortByStatus(rows) : rows;
  return (
    <div className="table-wrap" role="region" aria-label={caption} tabIndex={0}>
      <table className="data">
        <caption>{caption}</caption>
        <thead>
          <Header locale={locale} variant={variant} />
        </thead>
        <tbody>
          {ordered.map((row, i) => (
            <tr
              key={`${row.metric}-${row.dimension}-${row.value}-${String(i)}`}
              data-status={row.status}
            >
              <Name row={row} locale={locale} labels={labels} />
              <td className="num">{formatValue(row.baseline_mean, locale)}</td>
              <td className="num">{formatValue(row.candidate_mean, locale)}</td>
              {variant === "gated" ? (
                <>
                  <td className="num">{formatDeltaCi(row.result, locale)}</td>
                  <td className="num">
                    <ThresholdCell value={row.max_drop} locale={locale} />
                  </td>
                  <td className="num">{formatPlain(row.mde, locale)}</td>
                  <td>
                    <StatusBadge status={row.status} size="sm" />
                  </td>
                </>
              ) : (
                <>
                  <td className="num">{formatDelta(row.result?.mean_diff, locale)}</td>
                  <td className="num">{formatPlain(row.mde, locale)}</td>
                  <td className="num">
                    <ThresholdCell value={row.max_value} locale={locale} />
                  </td>
                  <td>{reasonLabel(locale, labels, reasonCode(row))}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
