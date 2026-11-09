import type { GateStatus } from "@/lib/types";

import { Icon, type IconName } from "./icons";

export type BadgeStatus = GateStatus | "NOT_GATED" | "NO_BASELINE";
export type BadgeSize = "sm" | "md" | "lg";

interface Meta {
  word: string;
  tone: "pass" | "warn" | "fail" | "neutral";
  icon: IconName;
}

/** Status words are product terms and are not translated (ui-spec §10.3). */
const META: Record<BadgeStatus, Meta> = {
  pass: { word: "PASS", tone: "pass", icon: "check-circle" },
  warn: { word: "WARN", tone: "warn", icon: "alert-triangle" },
  fail: { word: "FAIL", tone: "fail", icon: "x-circle" },
  insufficient_data: { word: "INSUFFICIENT DATA", tone: "neutral", icon: "circle-dashed" },
  unsupported_config: { word: "UNSUPPORTED CONFIG", tone: "warn", icon: "alert-octagon" },
  NOT_GATED: { word: "NOT GATED", tone: "neutral", icon: "circle" },
  NO_BASELINE: { word: "NO BASELINE", tone: "neutral", icon: "circle-slash" },
};

export interface StatusBadgeProps {
  status: BadgeStatus;
  size?: BadgeSize;
}

/** Icon + word, never colour alone: the icon is decorative and the word is the accessible name. */
export function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const meta = META[status];
  return (
    <span className={`badge badge--${meta.tone} badge--${size}`} data-status={status}>
      <Icon name={meta.icon} />
      <span>{meta.word}</span>
    </span>
  );
}

/** The badge a list row or summary shows for a run (ui-spec §4.1: no baseline first, then not gated). */
export function badgeFor(run: { status: GateStatus | null; no_baseline?: boolean }): BadgeStatus {
  if (run.no_baseline === true) return "NO_BASELINE";
  return run.status ?? "NOT_GATED";
}
