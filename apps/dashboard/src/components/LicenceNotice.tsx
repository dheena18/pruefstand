import { t, type Locale } from "@/lib/i18n";
import type { Licences } from "@/lib/site";

import { DataTable, type Column } from "./DataTable";

type Source = Licences["sources"][number];

export interface LicenceNoticeProps {
  locale: Locale;
  licences: Licences;
  /** `compact`: the attribution line only (footer, Try it). `full`: the `/licences/` page body. */
  variant?: "compact" | "full";
}

function columns(locale: Locale): Column<Source>[] {
  return [
    { id: "source", header: t(locale, "licences.col.source"), render: (s) => s.name },
    {
      id: "shown",
      header: t(locale, "licences.col.shown"),
      render: (s) => (
        <>
          <span aria-hidden="true">{s.shown_here ? "✓" : "–"}</span>
          <span className="sr-only">
            {t(locale, s.shown_here ? "licences.shown_yes" : "licences.shown_no")}
          </span>
        </>
      ),
    },
    {
      id: "licence",
      header: t(locale, "licences.col.licence"),
      render: (s) => <a href={s.licence_url}>{s.licence}</a>,
    },
    {
      id: "attribution",
      header: t(locale, "licences.col.attribution"),
      render: (s) => s.attribution,
    },
    {
      id: "link",
      header: t(locale, "licences.col.link"),
      render: (s) => <a href={s.url}>{s.url.replace(/^https?:\/\//, "")}</a>,
    },
  ];
}

/** Attribution line, or the full source table with the ODbL notice and the offer of the derived database. */
export function LicenceNotice({ locale, licences, variant = "full" }: LicenceNoticeProps) {
  if (variant === "compact") return <p lang={locale}>{licences.footer_line[locale]}</p>;
  return (
    <>
      <p lang={locale}>{licences.footer_line[locale]}</p>
      <DataTable
        label={t(locale, "licences.title")}
        columns={columns(locale)}
        rows={licences.sources}
        rowKey={(s) => s.id}
        card={(s) => (
          <>
            <strong>{s.name}</strong>
            <span>
              <a href={s.licence_url}>{s.licence}</a>
            </span>
            <span>{s.attribution}</span>
            <a href={s.url}>{s.url.replace(/^https?:\/\//, "")}</a>
          </>
        )}
      />
      <p lang="en" className="odbl-offer">
        {licences.odbl_offer}
      </p>
    </>
  );
}
