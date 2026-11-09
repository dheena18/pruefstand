import { defaultDataDir, loadCaseShard, loadRunIndex } from "./data";
import { NotFoundError } from "./errors";
import { EMPTY_ID } from "./ids";
import { LOCALES } from "./i18n";
import type { DashboardCases } from "./types";

/**
 * Static params of the pages below `runs/[id]/` (ui-spec §2.1, UI12-08): each page generates its own set from the
 * build-time data and falls back to the `_empty` placeholder when that set is empty (`output: "export"` rejects `[]`).
 */

/** Both locales × the given param sets; an empty set → one `_empty` placeholder per locale. */
export function forLocales<T extends object>(
  items: T[],
  placeholder: T,
): ({ locale: string } & T)[] {
  return LOCALES.flatMap((locale) =>
    (items.length === 0 ? [placeholder] : items).map((item) => ({ locale, ...item })),
  );
}

/** Runs with a `gate.json` that compared against a baseline: the runs that have Diff and Slices pages. */
export async function comparedRunIds(dir: string = defaultDataDir()): Promise<string[]> {
  const { runs } = await loadRunIndex(dir);
  return runs.filter((r) => r.status !== null && r.no_baseline !== true).map((r) => r.run_id);
}

/** Shard 0 of a run, or null when the run has no published case shards (`S-CASES-PRUNED`). */
export async function shardZero(
  id: string,
  dir: string = defaultDataDir(),
): Promise<DashboardCases | null> {
  try {
    return await loadCaseShard(id, 0, dir);
  } catch (error) {
    if (error instanceof NotFoundError) return null;
    throw error;
  }
}

/** Runs whose case shards are published: the newest 20 of the export (ui-spec §2.3). */
export async function casePublishedRunIds(dir: string = defaultDataDir()): Promise<string[]> {
  const { runs } = await loadRunIndex(dir);
  const out: string[] = [];
  for (const run of runs) if ((await shardZero(run.run_id, dir)) !== null) out.push(run.run_id);
  return out;
}

export { EMPTY_ID };
