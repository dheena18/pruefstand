import Link from "next/link";

import { ruleLabel, metricLabel } from "@/lib/labels";
import { t, type Locale } from "@/lib/i18n";
import type { HardFailFinding, LabelsDocument } from "@/lib/types";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const EVIDENCE_MAX = 200;

export interface HardFailListProps {
  locale: Locale;
  labels: LabelsDocument;
  runId: string;
  hardFails: HardFailFinding[];
  /** `cases/<id>/0.json` exists; a pruned run has no case pages, so no `Open case` link (UI13-16). */
  casesPublished: boolean;
  /** `panel`: tier-2 section with its own `h2`; `findings`: the bare list under the tier-1 check row. */
  variant?: "panel" | "findings";
}

function Finding({ f, ...p }: { f: HardFailFinding } & HardFailListProps) {
  const linkable = p.casesPublished && SAFE_ID.test(f.case_id);
  return (
    <li className="finding">
      <strong>
        {ruleLabel(p.locale, p.labels, f.rule, f.metric)}
        {f.rule === "hard_fail" ? "" : ` ${t(p.locale, "finding.unverifiable")}`}
      </strong>
      <span>
        {t(p.locale, "col.case")} <span className="mono">{f.case_id}</span>
      </span>
      <span>
        {t(p.locale, "col.metric")} {metricLabel(p.locale, p.labels, f.metric)}
      </span>
      <q lang="de" className="mono evidence">
        {f.evidence.slice(0, EVIDENCE_MAX)}
      </q>
      {linkable ? (
        <Link href={`/${p.locale}/runs/${p.runId}/cases/${f.case_id}/`}>
          {t(p.locale, "summary.open_case")} →
        </Link>
      ) : null}
    </li>
  );
}

/** Hard-fail findings: rule label, case, metric, redacted evidence in German (`lang="de"`). */
export function HardFailList(props: HardFailListProps) {
  const { hardFails, variant = "panel", locale } = props;
  if (hardFails.length === 0) return null;
  const title = t(locale, "summary.hard_fails", { n: hardFails.length });
  const list = (
    <ul className="findings" aria-label={variant === "findings" ? title : undefined}>
      {hardFails.map((f, i) => (
        <Finding key={`${f.case_id}-${String(i)}`} f={f} {...props} />
      ))}
    </ul>
  );
  if (variant === "findings") return list;
  return (
    <section className="panel-fail" aria-labelledby="hard-fails-h">
      <h2 id="hard-fails-h">{title}</h2>
      {list}
    </section>
  );
}
