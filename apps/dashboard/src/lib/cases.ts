import type { DashboardCase, DashboardCases } from "@/lib/types";

import { ShardLoadError, validateShard } from "./cases-validate";
import { dataUrl } from "./data-url";

export { ShardLoadError, validateShard };
export type { ShardFailure } from "./cases-validate";

/**
 * Runtime loader of the sharded case files (ui-spec §4.5.1): shard 0 first, then shards 1…n−1 in parallel,
 * each with a timeout, a structural validation and a retry. Presentation only: nothing here computes a metric.
 *
 * The build-time validator (Ajv) cannot run in the browser: it compiles schemas with `new Function`, which the
 * site's CSP forbids (`script-src` has no `'unsafe-eval'`, ui-spec §7.4). `validateShard` therefore checks the
 * same structure by hand; a shard that fails it is a failed shard (`C-SHARD-ERROR`).
 */

/** A shard fetch that does not settle within this time is a failed shard (ui-spec §4.5.1). */
export const SHARD_TIMEOUT_MS = 15000;

/** The baseline run's copy of a case for the answer pair: found, not exported, still loading, or failed. */
export type BaselineState =
  | { state: "found"; value: DashboardCase }
  | { state: "missing" }
  | { state: "loading" }
  | { state: "error" };

/** The part of `fetch` the loader uses (tests pass a function that serves the real fixture files). */
export type FetchLike = (
  url: string,
  init?: { signal?: AbortSignal },
) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;

type Cache = Map<string, Promise<DashboardCases>>;
const SHARED: Cache = new Map();

/** Forget every loaded shard (tests). */
export function clearShardCache(): void {
  SHARED.clear();
}

export interface LoadOptions {
  fetchImpl?: FetchLike | undefined;
  timeoutMs?: number | undefined;
  /** `basePath`; defaults to the build's. */
  base?: string | undefined;
  cache?: Cache | undefined;
}

async function fetchShard(runId: string, shard: number, o: LoadOptions): Promise<DashboardCases> {
  const fetchImpl: FetchLike = o.fetchImpl ?? ((url, init) => fetch(url, init));
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new ShardLoadError("timeout", shard, `shard ${String(shard)}: timed out`));
    }, o.timeoutMs ?? SHARD_TIMEOUT_MS);
  });
  const work = (async () => {
    const url = dataUrl(`cases/${runId}/${String(shard)}.json`, o.base);
    let response;
    try {
      response = await fetchImpl(url, { signal: controller.signal });
    } catch {
      throw new ShardLoadError("network", shard, `shard ${String(shard)}: request failed`);
    }
    if (!response.ok)
      throw new ShardLoadError(
        "network",
        shard,
        `shard ${String(shard)}: HTTP ${String(response.status)}`,
      );
    let json: unknown;
    try {
      json = await response.json();
    } catch {
      throw new ShardLoadError("invalid", shard, `shard ${String(shard)}: not JSON`);
    }
    return validateShard(json, runId, shard);
  })();
  try {
    return await Promise.race([work, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Fetch, validate and cache one shard. A successful shard is cached for the page's lifetime; a failed one is not,
 * so a retry fetches again.
 *
 * @throws ShardLoadError `network`, `timeout` or `invalid`.
 */
export function loadShard(
  runId: string,
  shard: number,
  o: LoadOptions = {},
): Promise<DashboardCases> {
  const cache = o.cache ?? SHARED;
  const key = `${runId}/${String(shard)}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const pending = fetchShard(runId, shard, o);
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

export interface ShardsState {
  readonly nShards: number;
  /** Cases of each loaded shard by number; `undefined` while not loaded. */
  readonly shards: readonly (readonly DashboardCase[] | undefined)[];
  /** Shards that failed (network, timeout or validation), ascending. */
  readonly failed: readonly number[];
  readonly loaded: number;
}

export interface StoreOptions extends LoadOptions {
  runId: string;
  nShards: number;
}

/**
 * Progressive loader state for one run: `start()` loads shard 0, then the rest in parallel; `retry(n)` reloads
 * a failed one. `getSnapshot` returns the same object until something changes (`useSyncExternalStore`).
 */
export class ShardStore {
  private state: ShardsState;
  private readonly listeners = new Set<() => void>();
  private readonly opts: StoreOptions;

  constructor(opts: StoreOptions) {
    this.opts = opts;
    this.state = {
      nShards: opts.nShards,
      shards: Array.from({ length: opts.nShards }, () => undefined),
      failed: [],
      loaded: 0,
    };
  }

  getSnapshot = (): ShardsState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private update(shard: number, cases: readonly DashboardCase[] | null): void {
    const shards = [...this.state.shards];
    if (cases !== null) shards[shard] = cases;
    const failed = this.state.failed.filter((n) => n !== shard);
    if (cases === null) failed.push(shard);
    failed.sort((a, b) => a - b);
    this.state = {
      ...this.state,
      shards,
      failed,
      loaded: shards.filter((s) => s !== undefined).length,
    };
    for (const listener of this.listeners) listener();
  }

  private async one(shard: number): Promise<void> {
    try {
      const loaded = await loadShard(this.opts.runId, shard, this.opts);
      if (loaded.n_shards !== this.opts.nShards) {
        throw new ShardLoadError("invalid", shard, "n_shards differs from the build");
      }
      this.update(shard, loaded.cases);
    } catch {
      this.update(shard, null);
    }
  }

  /** Load shard 0, then shards 1…n−1 in parallel; resolves when every one has settled. */
  async start(): Promise<void> {
    await this.one(0);
    const rest = Array.from({ length: this.opts.nShards - 1 }, (_, i) => this.one(i + 1));
    await Promise.all(rest);
  }

  /** Reload one (failed) shard. */
  retry(shard: number): Promise<void> {
    return this.one(shard);
  }
}

/** Failing first, then `case_id` by code point (R4 order; matches Python's sort). */
export function compareCases(a: DashboardCase, b: DashboardCase): number {
  if (a.failing !== b.failing) return a.failing ? -1 : 1;
  if (a.case_id === b.case_id) return 0;
  return a.case_id < b.case_id ? -1 : 1;
}

/** Loaded shards concatenated in shard order, then in the R4 sort order. */
export function mergedRows(state: ShardsState): DashboardCase[] {
  return state.shards.flatMap((s) => s ?? []).sort(compareCases);
}

export interface Totals {
  /** Sum of the loaded shard lengths (never `n_cases`, UI9-22). */
  total: number;
  loaded: number;
  nShards: number;
  partial: boolean;
}

export function summarize(state: ShardsState): Totals {
  const total = state.shards.reduce((sum, s) => sum + (s?.length ?? 0), 0);
  return {
    total,
    loaded: state.loaded,
    nShards: state.nShards,
    partial: state.loaded < state.nShards,
  };
}

/**
 * Find a case of the baseline run: its shards in order, the first hit wins (shard 0 first).
 *
 * @returns the case, or null when no loaded shard has it.
 * @throws ShardLoadError when a shard cannot be loaded before the case is found.
 */
export async function findBaselineCase(
  runId: string,
  nShards: number,
  caseId: string,
  o: LoadOptions = {},
): Promise<DashboardCase | null> {
  for (let shard = 0; shard < nShards; shard += 1) {
    const found = (await loadShard(runId, shard, o)).cases.find((c) => c.case_id === caseId);
    if (found !== undefined) return found;
  }
  return null;
}
