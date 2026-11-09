"use client";

import { useQueryString } from "@/lib/use-query";

import { DiffView, type DiffViewProps } from "./DiffView";

/** Client reader of `?sort=&slice=&page=` for the Diff page. */
export function DiffQuery(props: Omit<DiffViewProps, "query">) {
  return <DiffView {...props} query={useQueryString()} />;
}
