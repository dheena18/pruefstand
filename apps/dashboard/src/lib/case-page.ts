import type { BaselineState } from "./cases";
import { defaultDataDir, loadCaseShard } from "./data";
import { shardZero } from "./run-pages";
import type { RunContext } from "./run-context";

/** Baseline run and shard count for the runtime lookup, or null when its case shards are not exported. */
export async function baselineShards(
  ctx: RunContext,
  dir: string = defaultDataDir(),
): Promise<{ runId: string; nShards: number } | null> {
  if (ctx.baseline === null) return null;
  const first = await shardZero(ctx.baseline.run_id, dir);
  return first === null ? null : { runId: ctx.baseline.run_id, nShards: first.n_shards };
}

/** The baseline's copy of a case at build time (static case pages): its shards in order, first hit wins. */
export async function baselineCaseAtBuild(
  ctx: RunContext,
  caseId: string,
  dir: string = defaultDataDir(),
): Promise<BaselineState> {
  const baseline = await baselineShards(ctx, dir);
  if (baseline === null) return { state: "missing" };
  for (let shard = 0; shard < baseline.nShards; shard += 1) {
    const found = (await loadCaseShard(baseline.runId, shard, dir)).cases.find(
      (c) => c.case_id === caseId,
    );
    if (found !== undefined) return { state: "found", value: found };
  }
  return { state: "missing" };
}
