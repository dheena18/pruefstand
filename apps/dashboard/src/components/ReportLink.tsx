import { t, type Locale } from "@/lib/i18n";

export interface ReportLinkProps {
  locale: Locale;
  runId: string;
  basePath: string;
  /** `RunIndexEntry.status` (null = no `gate.json`). */
  status: string | null;
  /** `cases/<id>/0.json` exists at build time. */
  casesPublished: boolean;
}

/**
 * Open and Download of the static HTML report (ui-spec §4.9): only when the run has a gate report and is
 * case-published, because the export writes `report.html` in exactly that case. Plain `<a href>` elements,
 * never `next/link`: the target is outside the Next app and a client navigation would request an RSC payload.
 */
export function ReportLink({ locale, runId, basePath, status, casesPublished }: ReportLinkProps) {
  if (status === null || !casesPublished) return null;
  const href = `${basePath}/data/runs/${runId}/report.html`;
  return (
    <p className="report-links">
      <a href={href}>{t(locale, "summary.report_open")} ↗</a>
      <a href={href} download>
        {t(locale, "summary.report_download")}
      </a>
    </p>
  );
}
