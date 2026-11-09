import Link from "next/link";

import {
  formatCost,
  formatDuration,
  formatGpuSeconds,
  formatTokens,
  refLabel,
  totalTokens,
} from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";
import type { RunIndexEntry, RunManifest } from "@/lib/types";

export interface RunMetaBlockProps {
  locale: Locale;
  run: RunManifest;
  /** `gate.json` `baseline_run_id`, or null (no gate, or nothing compared). */
  baselineRunId: string | null;
  /** The baseline's index entry when it is in the export. */
  baseline: RunIndexEntry | null;
  /** `https://github.com/<owner>/<repo>`, for the PR link. */
  githubUrl: string;
}

const lowerEn = (locale: Locale, text: string): string =>
  locale === "en" ? text.toLowerCase() : text;

function Baseline({
  locale,
  baselineRunId,
  baseline,
}: Omit<RunMetaBlockProps, "run" | "githubUrl">) {
  if (baselineRunId === null) return <>–</>;
  if (baseline === null) return <span className="mono">{baselineRunId}</span>;
  return (
    <Link href={`/${locale}/runs/${baseline.run_id}/`} className="mono">
      {refLabel(baseline)}
    </Link>
  );
}

function workloadText(locale: Locale, run: RunManifest): string {
  const block = run.block == null ? "" : ` · ${t(locale, "summary.block", { k: run.block })}`;
  return `${lowerEn(locale, t(locale, "runs.col.workload"))} ${run.workload}${block}`;
}

/** `<dl>` of refs, size, cost, tokens, workload and judges (ui-spec §4.2, UI9-14, UI11-08, UI11-14, UI13-19). */
export function RunMetaBlock(props: RunMetaBlockProps) {
  const { locale, run, githubUrl } = props;
  const judges = Object.entries(run.judge_models);
  const tokens = formatTokens(totalTokens(run.cost), locale);
  return (
    <dl className="meta">
      <dt>{t(locale, "summary.baseline")}</dt>
      <dd>
        <Baseline {...props} />
      </dd>
      <dt>{t(locale, "summary.candidate")}</dt>
      <dd>
        <span className="mono">{refLabel(run)}</span>
        {run.pr_number == null ? null : (
          <>
            {" · "}
            <a href={`${githubUrl}/pull/${String(run.pr_number)}`}>PR #{run.pr_number} ↗</a>
          </>
        )}
      </dd>
      <dd>
        {run.splits.join(", ")} · {run.n_cases} {lowerEn(locale, t(locale, "runs.col.cases"))} ·{" "}
        {formatDuration(run.duration_s)} · {formatCost(run.cost.usd, locale)}
      </dd>
      <dd>
        {t(locale, "summary.tokens", { n: tokens })}
        {run.stack === "a40" ? ` · ${formatGpuSeconds(run.cost.gpu_seconds, locale)}` : ""} ·{" "}
        {workloadText(locale, run)}
      </dd>
      <dd>
        {judges.length === 0 ? null : (
          <>
            {t(locale, "summary.judges")}:{" "}
            <span className="mono">{judges.map(([k, v]) => `${k}=${v}`).join(", ")}</span>
            {" · "}
          </>
        )}
        {t(locale, "summary.judge_mode")} {run.judge_mode}
      </dd>
    </dl>
  );
}
