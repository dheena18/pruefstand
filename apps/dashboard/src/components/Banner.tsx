import type { BannerItem } from "@/lib/banners";
import { t, type Locale } from "@/lib/i18n";

import { Icon } from "./icons";

const MAX_VISIBLE = 3;

function One({ item }: { item: BannerItem }) {
  const role = item.severity === "error" ? "alert" : "status";
  const icon = item.severity === "info" ? "info" : "alert-triangle";
  return (
    <div className={`banner banner--${item.severity}`} role={role} data-state={item.id}>
      <Icon name={icon} />
      <p>{item.text}</p>
    </div>
  );
}

/** Banner zone: at most 3 visible, the rest behind a `<details>` disclosure (`banner.more`). */
export function Banner({ items, locale }: { items: BannerItem[]; locale: Locale }) {
  if (items.length === 0) return null;
  const shown = items.slice(0, MAX_VISIBLE);
  const rest = items.slice(MAX_VISIBLE);
  return (
    <div className="banner-zone">
      {shown.map((item) => (
        <One key={item.id} item={item} />
      ))}
      {rest.length === 0 ? null : (
        <details className="banner-more">
          <summary>{t(locale, "banner.more", { n: rest.length })}</summary>
          {rest.map((item) => (
            <One key={item.id} item={item} />
          ))}
        </details>
      )}
    </div>
  );
}
