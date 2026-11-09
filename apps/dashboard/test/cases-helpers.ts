import { readFile } from "node:fs/promises";
import path from "node:path";

import type { FetchLike } from "@/lib/cases";
import type { DashboardCase } from "@/lib/types";

import { POPULATED } from "./fixtures";

/** The 1,500-case fixture run (3 shards of 500); the real F-HARD-FAIL cases come first (SOURCE.md). */
export const D_MANY = "20261103T124330-75f7e3";

export function deferred<T = void>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const SHARD_URL = /\/data\/cases\/([^/]+)\/(\d+)\.json$/;
const FILES = new Map<string, string>();

/** Read shard files into memory first, so a test with fake timers does no real I/O while they run. */
export async function preload(runId: string, n = 3): Promise<void> {
  for (let i = 0; i < n; i += 1) {
    const file = path.join(POPULATED, "cases", runId, `${String(i)}.json`);
    FILES.set(`${runId}/${String(i)}`, await readFile(file, "utf8"));
  }
}

export interface FetchPlan {
  /** Shards (by number) whose response is held until the promise settles. */
  hold?: Record<number, Promise<unknown>>;
  /** Shards answered with HTTP 500. */
  fail?: number[];
  /** Transform the parsed JSON of a shard (e.g. to break it). */
  tamper?: Record<number, (json: Record<string, unknown>) => unknown>;
  /** Called with the shard number of every request, in order. */
  calls?: number[];
}

/** A `fetch` that serves the real fixture shard files, so loader tests read real data. */
export function fixtureFetch(plan: FetchPlan = {}): FetchLike {
  return async (url) => {
    const m = SHARD_URL.exec(url);
    if (m === null) return { ok: false, status: 404, json: () => Promise.resolve(null) };
    const shard = Number(m[2]);
    plan.calls?.push(shard);
    await plan.hold?.[shard];
    if (plan.fail?.includes(shard) === true) {
      return { ok: false, status: 500, json: () => Promise.resolve(null) };
    }
    const key = `${m[1] ?? ""}/${m[2] ?? ""}`;
    const text =
      FILES.get(key) ?? (await readFile(path.join(POPULATED, "cases", `${key}.json`), "utf8"));
    const json = JSON.parse(text) as Record<string, unknown>;
    const out = plan.tamper?.[shard]?.(json) ?? json;
    return { ok: true, status: 200, json: () => Promise.resolve(out) };
  };
}

export function makeCase(over: Partial<DashboardCase> = {}): DashboardCase {
  return {
    case_id: "law-0001",
    tenant: "kanzlei_mueller",
    lang: "de",
    category: "factual",
    perturbation: null,
    question: "Wann endet die Probezeit?",
    answer: "Nach sechs Monaten.",
    expect_refusal: false,
    refused: false,
    citations: ["§ 622 Abs. 3 BGB"],
    retrieved_chunk_ids: ["bgb-622#0", "kuendigung-intern#1"],
    retrieved_chunk_tenant_ids: ["shared_public", "kanzlei_mueller"],
    error: null,
    metric_values: { context_recall: 1, citation_f1: 0.5, ndcg_at_k: null },
    metric_status: { context_recall: "ok", citation_f1: "ok", ndcg_at_k: "not_applicable" },
    failing: false,
    ...over,
  };
}
