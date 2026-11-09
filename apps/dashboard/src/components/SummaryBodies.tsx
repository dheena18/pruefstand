import type { Partition } from "@/lib/summary";
import { isOverall, withReason } from "@/lib/summary";
import { t, type Locale } from "@/lib/i18n";
import type { GateReport, LabelsDocument, RunManifest } from "@/lib/types";

import { AbsoluteCheckTable } from "./AbsoluteCheckTable";
import { HardFailList } from "./HardFailList";
import { InformationalTable } from "./InformationalTable";
import { JudgedInfoTable } from "./JudgedInfoTable";
import { MetricTable } from "./MetricTable";
import { InsufficientLine, NotApplicableLine, NotableLine, TopFailing } from "./SummaryLists";
import { Tier1Notice } from "./Tier1Notice";

export interface BodyProps {
  locale: Locale;
  labels: LabelsDocument;
  run: RunManifest;
  gate: GateReport;
  blocks: Partition;
  casesPublished: boolean;
}

/** Tier-2 body (ui-spec §4.2.1): hard fails first, then blocks G, A, I, N, the two lines and top failing cases. */
export function Tier2Body({ locale, labels, run, gate, blocks, casesPublished }: BodyProps) {
  const graded = blocks.G.filter((d) => d.status !== "insufficient_data");
  const overall = graded.filter(isOverall);
  const others = graded.filter((d) => !isOverall(d) && d.status !== "pass");
  const common = { locale, labels };
  return (
    <>
      <HardFailList
        {...common}
        runId={run.run_id}
        hardFails={gate.hard_fails}
        casesPublished={casesPublished}
      />
      {overall.length === 0 ? null : (
        <MetricTable
          {...common}
          rows={overall}
          variant="gated"
          caption={t(locale, "summary.gated")}
        />
      )}
      {others.length === 0 ? null : (
        <MetricTable
          {...common}
          rows={others}
          variant="gated"
          caption={t(locale, "summary.gated_slices")}
        />
      )}
      {blocks.A.length === 0 ? null : (
        <AbsoluteCheckTable {...common} rows={blocks.A} variant="tier2" />
      )}
      <InformationalTable {...common} rows={withReason(blocks.I)} />
      <NotableLine locale={locale} rows={blocks.N} />
      <NotApplicableLine {...common} gate={gate} />
      <InsufficientLine
        {...common}
        rows={blocks.G.filter((d) => d.status === "insufficient_data")}
      />
      <TopFailing
        {...common}
        ids={gate.top_failing_cases}
        runId={run.run_id}
        casesPublished={casesPublished}
      />
    </>
  );
}

/** Tier-1 body (ui-spec §4.2.2): notice, checks that decide, reported rows, other informational, judged. */
export function Tier1Body({ locale, labels, run, gate, blocks, casesPublished }: BodyProps) {
  const common = { locale, labels };
  const reported = blocks.R.filter(isOverall);
  return (
    <>
      <Tier1Notice locale={locale} splits={run.splits} n={run.n_cases} />
      <AbsoluteCheckTable
        {...common}
        rows={blocks.C}
        variant="tier1"
        hardFailCount={gate.hard_fails.length}
      />
      <HardFailList
        {...common}
        runId={run.run_id}
        hardFails={gate.hard_fails}
        casesPublished={casesPublished}
        variant="findings"
      />
      {blocks.G.length === 0 ? null : (
        <MetricTable
          {...common}
          rows={blocks.G}
          variant="gated"
          caption={t(locale, "summary.gated")}
        />
      )}
      {reported.length === 0 ? null : (
        <MetricTable
          {...common}
          rows={reported}
          variant="reported"
          caption={t(locale, "tier1.reported", { n: run.n_cases })}
        />
      )}
      <InformationalTable {...common} rows={withReason(blocks.I)} />
      <JudgedInfoTable
        {...common}
        rows={blocks.J.filter(isOverall)}
        judgeMode={run.judge_mode}
        judgedCases={run.judged_cases ?? 0}
        judgedSubset={run.judged_subset === true}
      />
      <NotableLine locale={locale} rows={blocks.N} />
      <InsufficientLine
        {...common}
        rows={blocks.G.filter((d) => d.status === "insufficient_data")}
      />
      <TopFailing
        {...common}
        ids={gate.top_failing_cases}
        runId={run.run_id}
        casesPublished={casesPublished}
      />
    </>
  );
}
