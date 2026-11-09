import Link from "next/link";

import { t, type Locale } from "@/lib/i18n";

export interface PaginationProps {
  locale: Locale;
  page: number;
  pages: number;
  /** Href of page `n` (the same path with the list query). Links, so the pages work before hydration too. */
  hrefFor: (n: number) => string;
}

/** `‹ Prev  1 2 3  Next ›`; the current page has `aria-current="page"`. Nothing for a single page. */
export function Pagination({ locale, page, pages, hrefFor }: PaginationProps) {
  if (pages <= 1) return null;
  const numbers = Array.from({ length: pages }, (_, i) => i + 1);
  return (
    <nav className="pagination" aria-label={t(locale, "pagination.label")}>
      {page > 1 ? (
        <Link href={hrefFor(page - 1)} scroll={false} rel="prev">
          ‹ {t(locale, "pagination.prev")}
        </Link>
      ) : (
        <span aria-disabled="true">‹ {t(locale, "pagination.prev")}</span>
      )}
      {numbers.map((n) => (
        <Link
          key={n}
          href={hrefFor(n)}
          scroll={false}
          aria-current={n === page ? "page" : undefined}
        >
          {n}
        </Link>
      ))}
      {page < pages ? (
        <Link href={hrefFor(page + 1)} scroll={false} rel="next">
          {t(locale, "pagination.next")} ›
        </Link>
      ) : (
        <span aria-disabled="true">{t(locale, "pagination.next")} ›</span>
      )}
    </nav>
  );
}
