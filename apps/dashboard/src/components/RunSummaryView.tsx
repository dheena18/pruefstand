import Link from "next/link";

import { summaryBanners } from "@/lib/banners";
import { refLabel } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import type { RunContext } from "@/lib/run-context";
import { blockingCount, partition } from "@/lib/summary";

import { Banner } from "./Banner";
import { HardFailList } from "./HardFailList";
import { ReportLink } from "./ReportLink";
import { RunMetaBlock } from "./RunMetaBlock";
import { RunSubNav } from "./RunSubNav";
import { SummaryHeader } from "./SummaryHeader";
import { Tier1Body, Tier2Body } from "./SummaryBodies";
import { formatDate } from "@/lib/format";

export interface RunSummaryViewProps {
  locale: Locale;
  ctx: RunContext;
  basePath: string;
  githubUrl: string;
}

function Counts({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;
  return (
    <dl className="counts">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt className="mono">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The run summary (ui-spec §4.2): header, meta, banners, sub-nav and the tier-1 or tier-2 body. */
export function RunSummaryView({ locale, ctx, basePath, githubUrl }: RunSummaryViewProps) {
  const { entry, run, gate, labels, baseline, casesPublished, failing } = ctx;
  const blocks = gate === null ? null : partition(gate, run.stack);
  const blocking = gate === null || blocks === null ? 0 : blockingCount(gate, blocks);
  const banners = summaryBanners({ locale, run, gate, baselineInIndex: baseline !== null });
  const common = { locale, labels };
  const noBaseline = gate?.no_baseline === true;
  return (
    <>
      <nav aria-label="breadcrumb" className="breadcrumb">
        <Link href={`/${locale}/`}>{t(locale, "nav.runs")}</Link> ›{" "}
        <span className="mono">{refLabel(run)}</span> ({formatDate(run.created_at, locale)})
      </nav>
      <h1 className="sr-only">
        {t(locale, "nav.runs")} {refLabel(run)}
      </h1>
      <div className="summary-head">
        <SummaryHeader {...common} stack={run.stack} gate={gate} blocking={blocking} />
        <RunMetaBlock
          locale={locale}
          run={run}
          baselineRunId={gate?.baseline_run_id ?? null}
          baseline={baseline}
          githubUrl={githubUrl}
        />
      </div>
      <Banner items={banners} locale={locale} />
      <RunSubNav
        locale={locale}
        runId={run.run_id}
        active="summary"
        failing={failing}
        gated={gate !== null}
        noBaseline={noBaseline}
        casesPublished={casesPublished}
      />
      {gate === null || blocks === null ? (
        <Counts counts={run.counts} />
      ) : noBaseline ? (
        <HardFailList
          {...common}
          runId={run.run_id}
          hardFails={gate.hard_fails}
          casesPublished={casesPublished}
        />
      ) : run.stack === "live" ? (
        <Tier1Body
          {...common}
          run={run}
          gate={gate}
          blocks={blocks}
          casesPublished={casesPublished}
        />
      ) : (
        <Tier2Body
          {...common}
          run={run}
          gate={gate}
          blocks={blocks}
          casesPublished={casesPublished}
        />
      )}
      <div className="summary-actions">
        <ReportLink
          locale={locale}
          runId={run.run_id}
          basePath={basePath}
          status={entry.status}
          casesPublished={casesPublished}
        />
        {gate === null || noBaseline ? null : (
          <Link href={`/${locale}/runs/${run.run_id}/diff/`}>
            {t(locale, "summary.view_diff")} →
          </Link>
        )}
      </div>
    </>
  );
}
