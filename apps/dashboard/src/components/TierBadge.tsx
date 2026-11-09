import { t, type Locale } from "@/lib/i18n";

/** "Tier 1" (`live`) or "Tier 2" (`a40`); text, never colour alone. */
export function TierBadge({ stack, locale }: { stack: "live" | "a40"; locale: Locale }) {
  return (
    <span className="tier-badge">
      {t(locale, "runs.col.tier")} {stack === "live" ? "1" : "2"}
    </span>
  );
}
