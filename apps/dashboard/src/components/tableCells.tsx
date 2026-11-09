import { formatPlain } from "@/lib/format";
import { t, type Locale } from "@/lib/i18n";

/** A δ / Max cell: the value, or `–` with a visually hidden "no threshold" (ui-spec §4.2.1). */
export function ThresholdCell({
  value,
  locale,
}: {
  value: number | null | undefined;
  locale: Locale;
}) {
  if (value == null) {
    return (
      <>
        <span aria-hidden="true">–</span>
        <span className="sr-only">{t(locale, "diff.no_threshold")}</span>
      </>
    );
  }
  return <>{formatPlain(value, locale)}</>;
}
