import { t, type Locale } from "@/lib/i18n";

import { EmptyState } from "./EmptyState";

/** `E-PLACEHOLDER` of a page without real params (`runs/_empty/**`): `empty.runs`, a link to the runs list. */
export function RunsPlaceholder({ locale }: { locale: Locale }) {
  return (
    <EmptyState
      title={t(locale, "empty.runs")}
      text={t(locale, "empty.runs_hint")}
      action={{ href: `/${locale}/`, label: t(locale, "nav.runs") }}
    />
  );
}
