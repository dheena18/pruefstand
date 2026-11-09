import type { GateReport, RunManifest } from "@/lib/types";

import { t, type Locale } from "./i18n";

/** The banner zone of the run summary (ui-spec §4.2), in table order. */

export type Severity = "info" | "warn" | "error";
export interface BannerItem {
  id: string;
  severity: Severity;
  text: string;
}

export interface BannerInput {
  locale: Locale;
  run: RunManifest;
  gate: GateReport | null;
  /** Whether the baseline run (`gate.baseline_run_id`) is in the exported index. */
  baselineInIndex: boolean;
}

/**
 * `stop_reason.<code>`, except an aborted run with `infra_error` set → `stop_reason.aborted_infra`.
 * Only whether `infra_error` is set is read; its value is never rendered (UI12-16).
 */
export function stopReasonText(locale: Locale, run: RunManifest): string {
  const infra = run.stop_reason === "aborted" && run.infra_error != null && run.infra_error !== "";
  return t(locale, infra ? "stop_reason.aborted_infra" : `stop_reason.${run.stop_reason}`);
}

export function summaryBanners({ locale, run, gate, baselineInIndex }: BannerInput): BannerItem[] {
  const items: BannerItem[] = [];
  const add = (id: string, severity: Severity, key: string, params = {}) =>
    items.push({ id, severity, text: t(locale, key, params) });
  if (!run.complete) {
    add("S-PARTIAL", "warn", "banner.incomplete", { reason: stopReasonText(locale, run) });
  } else if (gate === null) {
    add("S-NOT-GATED", "info", "banner.not_gated");
  }
  if (gate?.no_baseline === true) add("S-NO-BASELINE", "error", "banner.no_baseline");
  if (run.judge_mode === "skipped") add("S-JUDGE-SKIPPED", "info", "banner.judge_skipped");
  if (run.judge_fallback === true && run.stack === "a40")
    add("S-JUDGE-FALLBACK", "warn", "banner.judge_fallback");
  if (run.judge_degraded === true) add("S-JUDGE-DEGRADED", "warn", "banner.judge_degraded");
  if (run.judge_drift === true) add("S-JUDGE-DRIFT", "warn", "banner.judge_drift");
  if (gate?.status === "unsupported_config") add("S-UNSUPPORTED", "warn", "banner.unsupported");
  if (gate?.baseline_run_id != null && !baselineInIndex) {
    add("S-BASELINE-MISSING", "info", "banner.baseline_missing", { id: gate.baseline_run_id });
  }
  return items;
}
