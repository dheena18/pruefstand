"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

import type { Locale } from "@/lib/i18n";
import type { RunIndexEntry } from "@/lib/types";

import { RunsListView } from "./RunsListView";

/**
 * The client reader of the URL query (ui-spec §6, UI11-09): applies filters, sort and page after hydration and
 * marks `<main data-hydrated="true">` so Playwright can wait for it. Rendered inside a `<Suspense>` whose
 * fallback is the static default view, so the no-JS page already shows the list.
 */
export function RunsList({ locale, runs }: { locale: Locale; runs: RunIndexEntry[] }) {
  const params = useSearchParams();
  useEffect(() => {
    document.querySelector("main")?.setAttribute("data-hydrated", "true");
  }, []);
  return <RunsListView locale={locale} runs={runs} query={params.toString()} />;
}
