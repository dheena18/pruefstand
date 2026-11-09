import { t, type Locale } from "@/lib/i18n";

import { Icon } from "./icons";

/** Why tier 1 decides on hard fails and the error rate only (ui-spec §4.2.2); `role="note"`. */
export function Tier1Notice({
  locale,
  splits,
  n,
}: {
  locale: Locale;
  splits: string[];
  n: number;
}) {
  return (
    <div className="banner banner--info" role="note">
      <Icon name="info" />
      <p>{t(locale, "tier1.notice", { split: splits.join(", "), n })}</p>
    </div>
  );
}
