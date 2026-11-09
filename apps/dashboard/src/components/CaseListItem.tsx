import Link from "next/link";

import { t, type Locale } from "@/lib/i18n";
import type { DashboardCase } from "@/lib/types";

import { Icon } from "./icons";

export interface CaseListItemProps {
  locale: Locale;
  value: DashboardCase;
  /** Href that selects the case (`?case=<id>` with the rest of the query). */
  href: string;
  selected: boolean;
  /** Static case page; only failing cases have one. */
  pageHref: string | null;
}

/** One row of the cases list: status, id, tenant · category · lang, question; `[Page ↗]` for failing cases. */
export function CaseListItem({ locale, value, href, selected, pageHref }: CaseListItemProps) {
  return (
    <li className="case-item" data-failing={value.failing ? "true" : "false"}>
      <Link href={href} className="case-item__link" aria-current={selected ? "true" : undefined}>
        <span className="case-item__status">
          <Icon name={value.failing ? "x-circle" : "check-circle"} />
          {value.failing ? (
            <span>{t(locale, "case.failing_badge")}</span>
          ) : (
            <span className="sr-only">{t(locale, "case.passing_sr")}</span>
          )}
        </span>
        <span className="mono case-item__id">{value.case_id}</span>
        <span className="case-item__meta">
          {value.tenant} · {value.category} · {value.lang}
        </span>
        <span className="case-item__q" lang={value.lang}>
          {value.question}
        </span>
      </Link>
      {pageHref === null ? null : (
        <Link href={pageHref} className="case-item__page">
          {t(locale, "cases.page")} ↗
        </Link>
      )}
    </li>
  );
}
