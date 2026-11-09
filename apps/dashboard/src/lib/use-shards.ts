import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import type { DashboardCase } from "@/lib/types";

import { ShardStore, findBaselineCase, type BaselineState, type ShardsState } from "./cases";

/**
 * Progressive shard state of one run for a component: starts the loader once `live` is true (after hydration),
 * re-renders on every shard that settles, and exposes `retry` for a failed one (ui-spec §4.5.1).
 */
export function useShards(
  runId: string,
  nShards: number,
  live: boolean,
): { state: ShardsState; retry: (shard: number) => void } {
  const [store] = useState(() => new ShardStore({ runId, nShards }));
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  useEffect(() => {
    if (live) void store.start();
  }, [live, store]);
  const retry = useCallback((shard: number) => void store.retry(shard), [store]);
  return { state, retry };
}

/** The baseline run's copy of a case, loaded on demand (shard 0 first); `missing` when it is not exported. */
export function useBaselineCase(
  baseline: { runId: string; nShards: number } | null,
  caseId: string,
): BaselineState {
  const [found, setFound] = useState<{ key: string; value: DashboardCase | null | "error" } | null>(
    null,
  );
  const key = baseline === null ? "" : `${baseline.runId}/${caseId}`;
  useEffect(() => {
    if (baseline === null) return;
    let alive = true;
    findBaselineCase(baseline.runId, baseline.nShards, caseId)
      .then((value) => alive && setFound({ key, value }))
      .catch(() => alive && setFound({ key, value: "error" }));
    return () => {
      alive = false;
    };
  }, [baseline, caseId, key]);
  if (baseline === null) return { state: "missing" };
  if (found?.key !== key) return { state: "loading" };
  if (found.value === "error") return { state: "error" };
  return found.value === null ? { state: "missing" } : { state: "found", value: found.value };
}
