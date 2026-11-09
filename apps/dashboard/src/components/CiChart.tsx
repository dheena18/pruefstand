import { ciDomain } from "@/lib/diff";
import { t, type Locale } from "@/lib/i18n";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

import { ChartShell } from "./ChartShell";
import { CiChartClient } from "./charts/CiChart.client";
import { MetricTable } from "./MetricTable";

export interface CiChartProps {
  locale: Locale;
  labels: LabelsDocument;
  /** The rows of this chart, already filtered, sorted and paged (≤ 50). */
  rows: SliceDecision[];
  /** Shared x domain of all pages of the chart; derived from `rows` when absent. */
  domain?: [number, number];
}

/**
 * Diff chart (ui-spec §4.3, §8): a figure with the dot-and-whisker plot (client-only) and the always-present
 * server-rendered Gated table (the table alternative, ui-spec §11.1 block G).
 */
export function CiChart({ locale, labels, rows, domain }: CiChartProps) {
  const shared = domain ?? ciDomain(rows);
  return (
    <ChartShell
      locale={locale}
      caption={`${t(locale, "diff.caption")} (${t(locale, "diff.axis")})`}
      chart={<CiChartClient locale={locale} labels={labels} rows={rows} domain={shared} />}
      table={
        <MetricTable
          locale={locale}
          labels={labels}
          rows={rows}
          variant="gated"
          caption={t(locale, "summary.gated")}
          keepOrder
        />
      }
    />
  );
}
