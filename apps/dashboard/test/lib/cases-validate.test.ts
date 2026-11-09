import { describe, expect, it } from "vitest";

import { ShardStore } from "@/lib/cases";
import { MAX_SHARD_CASES, validateShard } from "@/lib/cases-validate";

import { D_MANY, fixtureFetch, makeCase } from "../cases-helpers";

const shard = (cases: unknown[] = [makeCase()], extra: Record<string, unknown> = {}) => ({
  schema_version: "1",
  run_id: "r",
  shard: 0,
  n_shards: 1,
  cases,
  ...extra,
});
const bad = (data: unknown, message: RegExp) =>
  expect(() => validateShard(data, "r", 0)).toThrow(message);
const withCase = (over: Record<string, unknown>) => shard([{ ...makeCase(), ...over }]);

describe("validateShard mirrors dashboard_cases.schema.json", () => {
  it("accepts a valid shard", () => {
    expect(validateShard(shard(), "r", 0).cases).toHaveLength(1);
  });
  it("rejects an unknown key at the top level and in a case", () => {
    bad(shard([makeCase()], { surprise: 1 }), /unknown key "surprise"/);
    bad(withCase({ extra_field: "x" }), /unknown key "extra_field"/);
  });
  it("rejects a missing key at the top level and in a case", () => {
    const noN: Record<string, unknown> = { ...shard() };
    delete noN["n_shards"];
    bad(noN, /missing key "n_shards"/);
    const c: Record<string, unknown> = { ...makeCase() };
    delete c["tenant"];
    bad(shard([c]), /missing key "tenant"/);
  });
  it("rejects more than MAX_SHARD_CASES cases (oversized shard)", () => {
    const many = Array.from({ length: MAX_SHARD_CASES + 1 }, (_, i) =>
      makeCase({ case_id: `c-${String(i)}` }),
    );
    bad(shard(many), /more than 500 cases/);
    const ok = many.slice(0, MAX_SHARD_CASES);
    expect(validateShard(shard(ok), "r", 0).cases).toHaveLength(MAX_SHARD_CASES);
  });
  it("rejects a bad category and a bad metric_status value", () => {
    bad(withCase({ category: "nonsense" }), /category is unknown/);
    bad(withCase({ metric_status: { context_recall: "bogus" } }), /metric_status/);
    bad(withCase({ metric_status: "ok" }), /metric_status/);
    bad(withCase({ metric_values: { context_recall: "0.5" } }), /metric_values/);
  });
  it("rejects chunk id and tenant lists of different length; allows the pre-R3 empty tenant list", () => {
    bad(
      withCase({ retrieved_chunk_ids: ["a", "b"], retrieved_chunk_tenant_ids: ["x"] }),
      /not parallel/,
    );
    expect(validateShard(withCase({ retrieved_chunk_tenant_ids: [] }), "r", 0).cases).toHaveLength(
      1,
    );
  });
  it("rejects a duplicate case id inside a shard", () => {
    bad(shard([makeCase(), makeCase()]), /duplicate case_id/);
  });
});

describe("case ids are unique across shards", () => {
  it("a shard that repeats a case id of another shard is a failed shard", async () => {
    // slice-009 is the first real case of shard 0 in the 1,500-case fixture run
    const tamper = {
      1: (j: Record<string, unknown>) => ({
        ...j,
        cases: (j["cases"] as Record<string, unknown>[]).map((c, i) =>
          i === 0 ? { ...c, case_id: "slice-009" } : c,
        ),
      }),
    };
    const store = new ShardStore({
      runId: D_MANY,
      nShards: 3,
      fetchImpl: fixtureFetch({ tamper }),
      cache: new Map(),
    });
    await store.start();
    expect(store.getSnapshot().failed).toEqual([1]);
    expect(store.getSnapshot().loaded).toBe(2);
  });
});
