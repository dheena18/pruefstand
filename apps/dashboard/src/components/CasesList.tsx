"use client";

import { useQueryString } from "@/lib/use-query";

import { CasesView, type CasesViewProps } from "./CasesView";

/** Client reader of the cases-list URL query: applies it after hydration and starts the shard loader. */
export function CasesList(props: Omit<CasesViewProps, "query" | "live">) {
  return <CasesView {...props} query={useQueryString()} live />;
}
