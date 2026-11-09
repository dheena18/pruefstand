"use client";

import { useQueryString } from "@/lib/use-query";

import { SlicesView, type SlicesViewProps } from "./SlicesView";

/** Client reader of the per-section `?d_<id>=&m_<id>=` query for the Slices page. */
export function SlicesQuery(props: Omit<SlicesViewProps, "query">) {
  return <SlicesView {...props} query={useQueryString()} />;
}
