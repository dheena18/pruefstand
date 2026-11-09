import type { ReactNode, Ref } from "react";
import { createElement } from "react";
import Link from "next/link";

import { t, type Locale } from "@/lib/i18n";
import type { DashboardCase, HardFailFinding, LabelsDocument } from "@/lib/types";

import { AnswerPair, type BaselineState } from "./AnswerPair";
import { CaseMetrics } from "./CaseMetrics";
import { ChunkCard } from "./ChunkCard";
import { CitationList } from "./CitationList";
import { HardFailList } from "./HardFailList";

export interface CaseDetailProps {
  locale: Locale;
  labels: LabelsDocument;
  value: DashboardCase;
  baseline: BaselineState;
  /** The run's hard-fail findings for THIS case only. */
  hardFails: HardFailFinding[];
  /** `h1` on the static case page, `h2` in the list's panel (default). */
  level?: 1 | 2;
  /** Link to the static case page; only failing cases have one. */
  pageHref?: string | null;
  /** Buttons next to the title (copy link). */
  actions?: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
}

/** A confirmed leak: `hard_fail` on `tenant_leak`; an `…_unverifiable` finding is not a confirmed leak. */
const isTenantLeak = (f: HardFailFinding): boolean =>
  f.metric === "tenant_leak" && (f.rule === "hard_fail" || f.rule === "tenant_leak");

function Chunks({ locale, value }: { locale: Locale; value: DashboardCase }) {
  const tenants = value.retrieved_chunk_tenant_ids;
  return (
    <section className="case-section">
      <h3>{t(locale, "case.chunks")}</h3>
      <ol className="chunks">
        {value.retrieved_chunk_ids.map((id, i) => (
          <ChunkCard
            key={`${id}-${String(i)}`}
            locale={locale}
            rank={i + 1}
            chunkId={id}
            caseTenant={value.tenant}
            chunkTenant={tenants[i]}
          />
        ))}
      </ol>
    </section>
  );
}

/**
 * Everything the exports say about one case (ui-spec §4.5.4): question, answers, citations, metrics, this case's
 * hard-fail findings and the retrieved chunks. All text renders as text. Used by the list's panel and the static
 * case pages.
 */
export function CaseDetail(props: CaseDetailProps) {
  const {
    locale,
    labels,
    value,
    baseline,
    hardFails,
    level = 2,
    pageHref = null,
    actions,
    headingRef,
  } = props;
  // Data exported before R3 has no chunk tenants: the leak then shows from the case's `tenant_leak` finding.
  const leakFromFinding =
    value.retrieved_chunk_tenant_ids.length === 0 && hardFails.some(isTenantLeak);
  return (
    <article className="case-detail" data-case={value.case_id}>
      <header className="case-detail__head">
        {createElement(
          `h${String(level)}`,
          { ref: headingRef, tabIndex: -1, className: "case-detail__title" },
          t(locale, "case.title", { id: value.case_id }),
        )}
        <div className="case-detail__actions">
          {actions}
          {pageHref == null ? null : <Link href={pageHref}>{t(locale, "cases.page")} ↗</Link>}
        </div>
      </header>
      <p className="case-meta">
        {t(locale, "case.meta", {
          tenant: value.tenant,
          category: value.category,
          lang: value.lang,
          perturbation: value.perturbation ?? "–",
        })}
        {value.expect_refusal ? ` · ${t(locale, "case.expected_refusal")}` : ""}
      </p>
      {leakFromFinding ? <p className="leak-note">{t(locale, "case.leak_in_case")}</p> : null}
      {hardFails.length === 0 ? null : (
        <section className="case-section panel-fail">
          <h3>{t(locale, "summary.hard_fails", { n: hardFails.length })}</h3>
          <HardFailList
            locale={locale}
            labels={labels}
            runId=""
            hardFails={hardFails}
            casesPublished={false}
            variant="findings"
          />
        </section>
      )}
      <section className="case-section">
        <h3>{t(locale, "case.question")}</h3>
        <p lang={value.lang} className="case-text pre-wrap">
          {value.question}
        </p>
      </section>
      <AnswerPair locale={locale} value={value} baseline={baseline} />
      <section className="case-section">
        <h3>{t(locale, "case.citations")}</h3>
        <CitationList locale={locale} citations={value.citations} />
      </section>
      <CaseMetrics locale={locale} labels={labels} value={value} baseline={baseline} />
      <Chunks locale={locale} value={value} />
    </article>
  );
}
