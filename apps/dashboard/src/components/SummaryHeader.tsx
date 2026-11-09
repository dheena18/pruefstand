import { causeLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import type { GateReport, LabelsDocument } from "@/lib/types";

import { StatusBadge, badgeFor } from "./StatusBadge";
import { TierBadge } from "./TierBadge";

export interface SummaryHeaderProps {
  locale: Locale;
  labels: LabelsDocument;
  stack: "live" | "a40";
  gate: GateReport | null;
  /** Blocking issues (hard fails + FAIL rows of the Gated table). */
  blocking: number;
}

/** Status block: badge + tier, blocking count (or "nothing compared"), likely cause (ui-spec §4.2). */
export function SummaryHeader({ locale, labels, stack, gate, blocking }: SummaryHeaderProps) {
  const badge =
    gate === null
      ? "NOT_GATED"
      : badgeFor({ status: gate.status, no_baseline: gate.no_baseline === true });
  const noBaseline = gate?.no_baseline === true;
  return (
    <div className="summary-status">
      <div className="summary-status__badge">
        <StatusBadge status={badge} size="lg" />
        <TierBadge stack={stack} locale={locale} />
      </div>
      {gate === null ? null : (
        <p className="summary-status__count">
          {noBaseline
            ? t(locale, "summary.nothing_compared")
            : t(locale, "summary.blocking", { n: blocking })}
        </p>
      )}
      {gate?.likely_cause == null ? null : (
        <p>
          {t(locale, "summary.likely_cause", {
            cause: causeLabel(locale, labels, gate.likely_cause),
          })}
        </p>
      )}
    </div>
  );
}
