"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { LOCALES, t, type Locale } from "@/lib/i18n";

/** The same path in the other locale (`/de/runs/x/` → `/en/runs/x/`); query and hash are appended by the caller. */
export function switchedPath(pathname: string, target: Locale): string {
  const rest = pathname.replace(/^\/(de|en)(?=\/|$)/, "");
  return `/${target}${rest === "" ? "/" : rest}`;
}

export interface LocaleSwitchViewProps {
  locale: Locale;
  pathname: string;
  /** `?a=b` or empty. */
  search: string;
}

/** Two links to the same path and query in each locale. Stores nothing (ui-spec §2.2). */
export function LocaleSwitchView({ locale, pathname, search }: LocaleSwitchViewProps) {
  return (
    <nav className="locale-switch" aria-label={t(locale, "locale.switch")}>
      {LOCALES.map((code) =>
        code === locale ? (
          <span key={code} lang={code} aria-current="true">
            {code.toUpperCase()}
          </span>
        ) : (
          <Link
            key={code}
            href={`${switchedPath(pathname, code)}${search}`}
            hrefLang={code}
            lang={code}
          >
            {code.toUpperCase()}
          </Link>
        ),
      )}
    </nav>
  );
}

/** Static HTML has no query; after hydration the current query is added to both links. */
export function LocaleSwitch({ locale }: { locale: Locale }) {
  const pathname = usePathname();
  const [search, setSearch] = useState("");
  useEffect(() => {
    setSearch(window.location.search);
  }, [pathname]);
  return <LocaleSwitchView locale={locale} pathname={pathname} search={search} />;
}
