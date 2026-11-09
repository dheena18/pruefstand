import type { DashboardCases } from "@/lib/types";

/** Hand-written structural validation of a case shard (browser side; Ajv cannot run under the site's CSP, D665). */

export type ShardFailure = "network" | "timeout" | "invalid";

export class ShardLoadError extends Error {
  readonly kind: ShardFailure;
  readonly shard: number;

  constructor(kind: ShardFailure, shard: number, message: string) {
    super(message);
    this.kind = kind;
    this.shard = shard;
    this.name = "ShardLoadError";
  }
}

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStrings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const isNullable = (v: unknown, type: "string" | "boolean"): boolean =>
  v === null || typeof v === type;
const CATEGORIES = new Set([
  "factual",
  "multi_hop",
  "comparison",
  "unanswerable",
  "cross_lingual",
  "injection",
  "leak_probe",
  "system_prompt_extraction",
  "filter_bypass",
]);
const STATUSES = new Set(["ok", "not_applicable", "error"]);

function caseProblem(c: unknown): string | null {
  if (!isObject(c)) return "case is not an object";
  const strings = ["case_id", "tenant", "question"];
  for (const key of strings) if (typeof c[key] !== "string") return `${key} is not a string`;
  for (const key of ["answer", "error", "perturbation"]) {
    if (!isNullable(c[key], "string")) return `${key} is not a string or null`;
  }
  for (const key of ["expect_refusal", "failing"]) {
    if (typeof c[key] !== "boolean") return `${key} is not a boolean`;
  }
  if (!isNullable(c["refused"], "boolean")) return "refused is not a boolean or null";
  if (c["lang"] !== "de" && c["lang"] !== "en") return "lang is not de or en";
  if (typeof c["category"] !== "string" || !CATEGORIES.has(c["category"]))
    return "category is unknown";
  for (const key of ["citations", "retrieved_chunk_ids", "retrieved_chunk_tenant_ids"]) {
    if (!isStrings(c[key])) return `${key} is not a list of strings`;
  }
  const values = c["metric_values"];
  const status = c["metric_status"];
  if (
    !isObject(values) ||
    !Object.values(values).every((v) => v === null || typeof v === "number")
  ) {
    return "metric_values is not a map of numbers";
  }
  if (
    !isObject(status) ||
    !Object.values(status).every((v) => typeof v === "string" && STATUSES.has(v))
  ) {
    return "metric_status is not a map of statuses";
  }
  return null;
}

/**
 * Check a parsed shard against `dashboard_cases.schema.json` by hand.
 *
 * @throws ShardLoadError kind `invalid`: an unknown `schema_version`, another run or shard than asked for,
 *   or a case of the wrong shape.
 */
export function validateShard(data: unknown, runId: string, shard: number): DashboardCases {
  const fail = (why: string): never => {
    throw new ShardLoadError("invalid", shard, `shard ${String(shard)}: ${why}`);
  };
  if (!isObject(data)) return fail("not an object");
  if (data["schema_version"] !== "1") fail("unknown schema_version");
  if (data["run_id"] !== runId) fail("run_id differs");
  if (data["shard"] !== shard) fail("shard number differs");
  const n = data["n_shards"];
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || shard >= n)
    fail("n_shards is wrong");
  const cases = data["cases"];
  if (!Array.isArray(cases)) return fail("cases is not a list");
  for (const c of cases) {
    const problem = caseProblem(c);
    if (problem !== null) fail(problem);
  }
  return data as unknown as DashboardCases;
}
