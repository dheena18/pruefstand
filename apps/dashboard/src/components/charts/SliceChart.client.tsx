"use client";

import dynamic from "next/dynamic";

import type { SlicePlotProps } from "../SlicePlot";

// `ssr: false` is only allowed in a Client Component in Next 15 (ui-spec §8, UI11-22).
const SlicePlot = dynamic(() => import("../SlicePlot"), { ssr: false, loading: () => null });

/** The slice bars, loaded in the browser only. */
export function SliceChartClient(props: SlicePlotProps) {
  return <SlicePlot {...props} />;
}
