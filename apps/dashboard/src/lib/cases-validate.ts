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

/** No shard has more cases than this (`validate_data.mjs` rule 4, ui-spec §2.3). */
export const MAX_SHARD_CASES = 500;

const TOP_KEYS = ["cases", "n_shards", "run_id", "schema_version", "shard"];
const CASE_KEYS = [
  "answer",
  "case_id",
  "category",
  "citations",
  "error",
  "expect_refusal",
  "failing",
  "lang",
  "metric_status",
  "metric_values",
  "perturbation",
  "question",
  "refused",
  "retrieved_chunk_ids",
  "retrieved_chunk_tenant_ids",
  "tenant",
];
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

/** `additionalProperties: false` and `required`: the object has exactly these keys. */
function keyProblem(o: Json, keys: readonly string[], what: string): string | null {
  const extra = Object.keys(o).find((k) => !keys.includes(k));
  if (extra !== undefined) return `${what}: unknown key ${JSON.stringify(extra)}`;
  const missing = keys.find((k) => !(k in o));
  return missing === undefined ? null : `${what}: missing key ${JSON.stringify(missing)}`;
}

function scalarProblem(c: Json): string | null {
  for (const key of ["case_id", "tenant", "question"]) {
    if (typeof c[key] !== "string") return `${key} is not a string`;
  }
  for (const key of ["answer", "error", "perturbation"]) {
    if (!isNullable(c[key], "string")) return `${key} is not a string or null`;
  }
  for (const key of ["expect_refusal", "failing"]) {
    if (typeof c[key] !== "boolean") return `${key} is not a boolean`;
  }
  if (!isNullable(c["refused"], "boolean")) return "refused is not a boolean or null";
  if (c["lang"] !== "de" && c["lang"] !== "en") return "lang is not de or en";
  if (typeof c["category"] !== "string" || !CATEGORIES.has(c["category"])) {
    return "category is unknown";
  }
  return null;
}

function collectionProblem(c: Json): string | null {
  for (const key of ["citations", "retrieved_chunk_ids", "retrieved_chunk_tenant_ids"]) {
    if (!isStrings(c[key])) return `${key} is not a list of strings`;
  }
  const ids = c["retrieved_chunk_ids"] as string[];
  const tenants = c["retrieved_chunk_tenant_ids"] as string[];
  // R3: parallel lists; data exported before R3 has an empty tenant list (ui-spec §4.5.4).
  if (tenants.length !== 0 && tenants.length !== ids.length) {
    return "retrieved_chunk_tenant_ids is not parallel to retrieved_chunk_ids";
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

function caseProblem(c: unknown): string | null {
  if (!isObject(c)) return "case is not an object";
  return keyProblem(c, CASE_KEYS, "case") ?? scalarProblem(c) ?? collectionProblem(c);
}

/**
 * Check a parsed shard against `dashboard_cases.schema.json` by hand: exact keys (no extra, none missing), types,
 * enums, at most `MAX_SHARD_CASES` cases, parallel chunk lists, unique case ids. (Ids across shards are checked by
 * `ShardStore`.)
 *
 * @throws ShardLoadError kind `invalid`: an unknown `schema_version`, another run or shard than asked for,
 *   or a shard or case of the wrong shape.
 */
export function validateShard(data: unknown, runId: string, shard: number): DashboardCases {
  const fail = (why: string): never => {
    throw new ShardLoadError("invalid", shard, `shard ${String(shard)}: ${why}`);
  };
  if (!isObject(data)) return fail("not an object");
  const keys = keyProblem(data, TOP_KEYS, "shard");
  if (keys !== null) fail(keys);
  if (data["schema_version"] !== "1") fail("unknown schema_version");
  if (data["run_id"] !== runId) fail("run_id differs");
  if (data["shard"] !== shard) fail("shard number differs");
  const n = data["n_shards"];
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1 || shard >= n)
    fail("n_shards is wrong");
  const cases = data["cases"];
  if (!Array.isArray(cases)) return fail("cases is not a list");
  if (cases.length > MAX_SHARD_CASES) fail(`more than ${String(MAX_SHARD_CASES)} cases`);
  const seen = new Set<string>();
  for (const c of cases) {
    const problem = caseProblem(c);
    if (problem !== null) fail(problem);
    const id = (c as { case_id: string }).case_id;
    if (seen.has(id)) fail(`duplicate case_id ${JSON.stringify(id)}`);
    seen.add(id);
  }
  return data as unknown as DashboardCases;
}
