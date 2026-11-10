"use client";

import dynamic from "next/dynamic";

import type { CiPlotProps } from "../CiPlot";

// Next 15 rejects `ssr: false` in Server Components, so the lazy import lives in this client file (ui-spec §8, UI11-22).
const CiPlot = dynamic(() => import("../CiPlot"), { ssr: false, loading: () => null });

/** The Diff plot, loaded in the browser only. */
export function CiChartClient(props: CiPlotProps) {
  return <CiPlot {...props} />;
}
