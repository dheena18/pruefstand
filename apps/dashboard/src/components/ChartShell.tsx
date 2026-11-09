"use client";

import { useEffect, useState, type ReactNode } from "react";

import { t, type Locale } from "@/lib/i18n";

export interface ChartShellProps {
  locale: Locale;
  caption: string;
  /** The client-only plot (a `charts/*.client` element); mounted only after hydration. */
  chart: ReactNode;
  /** The server-rendered table alternative: always in the DOM (WCAG 1.1.1, ui-spec §8). */
  table: ReactNode;
  /** Number of values when the chart shows fewer than all of them (the button then reads `slices.show_all`). */
  truncatedTo?: number | null;
}

/**
 * `<figure>` + `<figcaption>` + "Show as table" (ui-spec §8). Without JavaScript (and before hydration) the table
 * is the visible content; after hydration the chart shows and the table stays in the DOM, visually hidden, until
 * the toggle button is used.
 */
export function ChartShell({ locale, caption, chart, table, truncatedTo = null }: ChartShellProps) {
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<"chart" | "table">("chart");
  useEffect(() => setReady(true), []);
  const shown = ready ? view : "table";
  const label =
    view === "table"
      ? t(locale, "chart.show_chart")
      : truncatedTo === null
        ? t(locale, "chart.show_table")
        : t(locale, "slices.show_all", { n: truncatedTo });
  return (
    <figure className="chart" data-view={shown}>
      <figcaption>{caption}</figcaption>
      {ready ? (
        <div className="chart__plot" hidden={view === "table"}>
          {chart}
        </div>
      ) : null}
      <div className={shown === "table" ? "chart__table" : "sr-only"}>{table}</div>
      {ready ? (
        <button
          type="button"
          className="btn chart__toggle"
          onClick={() => setView(view === "chart" ? "table" : "chart")}
        >
          {label}
        </button>
      ) : null}
    </figure>
  );
}
