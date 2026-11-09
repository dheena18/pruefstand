import type { GateReport, LabelsDocument, RunIndexEntry, RunManifest } from "@/lib/types";

import { defaultDataDir, loadCaseShard, loadGate, loadLabels, loadRun, loadRunIndex } from "./data";
import { NotFoundError } from "./errors";

/** Everything a run page needs, read (and validated) at build time. */
export interface RunContext {
  entry: RunIndexEntry;
  run: RunManifest;
  /** Null when the run has no `gate.json` (`entry.status == null`). */
  gate: GateReport | null;
  labels: LabelsDocument;
  /** The baseline's index entry when `gate.baseline_run_id` is in the export. */
  baseline: RunIndexEntry | null;
  /** `cases/<id>/0.json` exists; false → `S-CASES-PRUNED` (known from the file's absence, ui-spec §4.2). */
  casesPublished: boolean;
  /** Failing rows of case shard 0 (R4 order puts every failing case there); 0 without cases. */
  failing: number;
}

/**
 * Load the context of run `id`.
 *
 * @throws NotFoundError when `id` is not in the index
 */
export async function loadRunContext(
  id: string,
  dir: string = defaultDataDir(),
): Promise<RunContext> {
  const index = await loadRunIndex(dir);
  const entry = index.runs.find((r) => r.run_id === id);
  if (entry === undefined) throw new NotFoundError(`run ${id} is not in the index`, id);
  const [run, labels] = await Promise.all([loadRun(id, dir), loadLabels(dir)]);
  const gate = entry.status === null ? null : await loadGate(id, dir);
  const baselineId = gate?.baseline_run_id ?? null;
  const baseline = index.runs.find((r) => r.run_id === baselineId) ?? null;
  let casesPublished = true;
  let failing = 0;
  try {
    const shard = await loadCaseShard(id, 0, dir);
    failing = shard.cases.filter((c) => c.failing).length;
  } catch (error) {
    if (!(error instanceof NotFoundError)) throw error;
    casesPublished = false;
  }
  return { entry, run, gate, labels, baseline, casesPublished, failing };
}
