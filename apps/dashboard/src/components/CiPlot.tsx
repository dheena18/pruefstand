import { formatDelta } from "@/lib/format";
import { metricLabel } from "@/lib/labels";
import type { Locale } from "@/lib/i18n";
import { sliceSuffix } from "@/lib/summary";
import type { LabelsDocument, SliceDecision } from "@/lib/types";

import { CiBar } from "./CiBar";
import { StatusBadge } from "./StatusBadge";

export interface CiPlotProps {
  locale: Locale;
  labels: LabelsDocument;
  rows: SliceDecision[];
  domain: [number, number];
}

function Axis({ locale, domain }: { locale: Locale; domain: [number, number] }) {
  const [lo, hi] = domain;
  const zero = hi === lo ? 50 : ((0 - lo) / (hi - lo)) * 100;
  return (
    <svg className="ciplot__axis" aria-hidden="true" width="100%" height={16} focusable="false">
      <text x="0%" y={12} textAnchor="start">
        {formatDelta(lo, locale)}
      </text>
      {zero > 12 && zero < 88 ? (
        <text x={`${zero.toFixed(3)}%`} y={12} textAnchor="middle">
          {formatDelta(0, locale)}
        </text>
      ) : null}
      <text x="100%" y={12} textAnchor="end">
        {formatDelta(hi, locale)}
      </text>
    </svg>
  );
}

/** The chart body of the Diff page: an axis and one `CiBar` row per gated pair. Loaded client-only (ui-spec §8). */
export default function CiPlot({ locale, labels, rows, domain }: CiPlotProps) {
  return (
    <div className="ciplot">
      <div className="ciplot__row ciplot__row--axis" aria-hidden="true">
        <span />
        <Axis locale={locale} domain={domain} />
        <span />
      </div>
      <ul className="ciplot__rows">
        {rows.map((row, i) => (
          <li
            key={`${row.metric}-${row.dimension}-${row.value}-${String(i)}`}
            className="ciplot__row"
            data-status={row.status}
          >
            <span className="ciplot__label">
              {metricLabel(locale, labels, row.metric)}
              {sliceSuffix(row) === "" ? null : <span className="mono">{sliceSuffix(row)}</span>}
              <StatusBadge status={row.status} size="sm" />
            </span>
            <CiBar locale={locale} row={row} domain={domain} />
          </li>
        ))}
      </ul>
    </div>
  );
}
