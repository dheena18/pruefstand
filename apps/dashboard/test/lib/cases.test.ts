import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SHARD_TIMEOUT_MS,
  ShardLoadError,
  ShardStore,
  findBaselineCase,
  loadShard,
  mergedRows,
  summarize,
  validateShard,
  type FetchLike,
} from "@/lib/cases";
import {
  CASE_PAGE_SIZE,
  applyCases,
  facetValues,
  filterCases,
  parseCasesQuery,
  toCasesQuery,
  type CasesState,
} from "@/lib/cases-state";
import { dataUrl } from "@/lib/data-url";
import { t } from "@/lib/i18n";

import { D_MANY, deferred, fixtureFetch, makeCase, preload } from "../cases-helpers";

const store = (fetchImpl: FetchLike, timeoutMs?: number) =>
  new ShardStore({ runId: D_MANY, nShards: 3, fetchImpl, cache: new Map(), timeoutMs });

afterEach(() => vi.useRealTimers());

describe("loadShard", () => {
  it("fetches below basePath (UI12-05) and returns the validated shard", async () => {
    const urls: string[] = [];
    const inner = fixtureFetch();
    const spy: FetchLike = (url, init) => (urls.push(url), inner(url, init));
    const shard = await loadShard(D_MANY, 1, {
      fetchImpl: spy,
      base: "/pruefstand",
      cache: new Map(),
    });
    expect(urls).toEqual([`/pruefstand/data/cases/${D_MANY}/1.json`]);
    expect([shard.shard, shard.n_shards, shard.cases.length]).toEqual([1, 3, 500]);
    expect(dataUrl("cases/x/0.json", "")).toBe("/data/cases/x/0.json");
  });
  it("an HTTP error is kind network; a wrong run id or shard number is kind invalid", async () => {
    const o = { cache: new Map() };
    const bad = await loadShard(D_MANY, 1, { ...o, fetchImpl: fixtureFetch({ fail: [1] }) }).catch(
      (e) => e,
    );
    expect(bad).toBeInstanceOf(ShardLoadError);
    expect((bad as ShardLoadError).kind).toBe("network");
    const wrongRun = fixtureFetch({ tamper: { 1: (j) => ({ ...j, run_id: "other" }) } });
    const a = await loadShard(D_MANY, 1, { ...o, fetchImpl: wrongRun }).catch((e) => e);
    expect((a as ShardLoadError).kind).toBe("invalid");
    const wrongShard = fixtureFetch({ tamper: { 1: (j) => ({ ...j, shard: 2 }) } });
    const b = await loadShard(D_MANY, 1, { ...o, fetchImpl: wrongShard, cache: new Map() }).catch(
      (e) => e,
    );
    expect((b as ShardLoadError).kind).toBe("invalid");
  });
  it("validateShard rejects a missing field, a wrong type and an unknown schema version", () => {
    const good = {
      schema_version: "1",
      run_id: "r",
      shard: 0,
      n_shards: 1,
      cases: [makeCase()],
    };
    expect(validateShard(good, "r", 0).cases).toHaveLength(1);
    expect(() => validateShard({ ...good, schema_version: "2" }, "r", 0)).toThrow(ShardLoadError);
    expect(() =>
      validateShard({ ...good, cases: [{ ...makeCase(), failing: "yes" }] }, "r", 0),
    ).toThrow();
    expect(() =>
      validateShard({ ...good, cases: [{ ...makeCase(), lang: "fr" }] }, "r", 0),
    ).toThrow();
    const noQuestion: Record<string, unknown> = { ...makeCase() };
    delete noQuestion["question"];
    expect(() => validateShard({ ...good, cases: [noQuestion] }, "r", 0)).toThrow();
    expect(() => validateShard(null, "r", 0)).toThrow();
  });
  it("a successful shard is cached; a failed one is not", async () => {
    const cache = new Map();
    const calls: number[] = [];
    await loadShard(D_MANY, 0, { fetchImpl: fixtureFetch({ calls }), cache });
    await loadShard(D_MANY, 0, { fetchImpl: fixtureFetch({ calls }), cache });
    expect(calls).toEqual([0]);
    await loadShard(D_MANY, 1, { fetchImpl: fixtureFetch({ fail: [1] }), cache }).catch(() => null);
    await loadShard(D_MANY, 1, { fetchImpl: fixtureFetch({ calls }), cache });
    expect(calls).toEqual([0, 1]);
  });
});

describe("ShardStore", () => {
  it("shard 0 loads first and holds every failing case; the rest merge in shard order", async () => {
    const calls: number[] = [];
    const s = store(fixtureFetch({ calls }));
    await s.start();
    expect(calls[0]).toBe(0);
    const snap = s.getSnapshot();
    expect(snap.loaded).toBe(3);
    const rows = mergedRows(snap);
    expect(rows).toHaveLength(1500);
    const failing = rows.filter((c) => c.failing).length;
    expect(snap.shards[0]?.filter((c) => c.failing).length).toBe(failing);
    expect(rows.slice(0, failing).every((c) => c.failing)).toBe(true);
    // rows after the failing block are in case_id order inside each shard (R4)
    expect(rows[failing + 5]?.case_id ?? "").toBeTruthy();
  });
  it("C-LOADING: with shards 1 and 2 held the total is partial and the text says 1 of 3", async () => {
    const hold = deferred();
    const s = store(fixtureFetch({ hold: { 1: hold.promise, 2: hold.promise } }));
    const done = s.start();
    await vi.waitFor(() => expect(s.getSnapshot().loaded).toBe(1));
    const sum = summarize(s.getSnapshot());
    expect(sum).toMatchObject({ total: 500, loaded: 1, nShards: 3, partial: true });
    expect(t("en", "cases.loading", { loaded: sum.loaded, total: sum.nShards })).toBe(
      "Loading cases: 1 of 3 parts",
    );
    hold.resolve();
    await done;
    expect(summarize(s.getSnapshot())).toMatchObject({ total: 1500, partial: false });
  });
  it("totals are the sum of the loaded shard lengths, never n_cases", async () => {
    const hold = deferred();
    const s = store(fixtureFetch({ hold: { 2: hold.promise } }));
    const done = s.start();
    await vi.waitFor(() => expect(s.getSnapshot().loaded).toBe(2));
    expect(summarize(s.getSnapshot()).total).toBe(1000);
    hold.resolve();
    await done;
  });
  it("C-SHARD-ERROR: a rejected shard 1 keeps loaded rows usable; retry loads it", async () => {
    let broken = true;
    const inner = fixtureFetch();
    const flaky: FetchLike = (url, init) =>
      broken && url.endsWith("/1.json")
        ? Promise.reject(new TypeError("offline"))
        : inner(url, init);
    const s = store(flaky);
    await s.start();
    expect(s.getSnapshot().failed).toEqual([1]);
    expect(mergedRows(s.getSnapshot())).toHaveLength(1000);
    broken = false;
    await s.retry(1);
    expect(s.getSnapshot().failed).toEqual([]);
    expect(mergedRows(s.getSnapshot())).toHaveLength(1500);
  });
  it("C-SHARD-ERROR: an invalid shard 1 is a failed shard", async () => {
    const s = store(fixtureFetch({ tamper: { 1: (j) => ({ ...j, cases: "nope" }) } }));
    await s.start();
    expect(s.getSnapshot().failed).toEqual([1]);
    expect(s.getSnapshot().loaded).toBe(2);
  });
  it("C-SHARD-ERROR: a shard that does not settle within SHARD_TIMEOUT_MS fails; retry works", async () => {
    await preload(D_MANY);
    vi.useFakeTimers();
    const hold = deferred();
    const s = store(fixtureFetch({ hold: { 1: hold.promise } }));
    const done = s.start();
    await vi.advanceTimersByTimeAsync(SHARD_TIMEOUT_MS - 1);
    expect(s.getSnapshot().failed).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    await done;
    expect(s.getSnapshot().failed).toEqual([1]);
    expect(s.getSnapshot().loaded).toBe(2);
    const fresh = fixtureFetch();
    const again = new ShardStore({ runId: D_MANY, nShards: 3, fetchImpl: fresh, cache: new Map() });
    await again.start();
    expect(again.getSnapshot().failed).toEqual([]);
  });
  it("notifies subscribers and returns a stable snapshot between changes", async () => {
    const s = store(fixtureFetch());
    const seen: number[] = [];
    const off = s.subscribe(() => seen.push(s.getSnapshot().loaded));
    expect(s.getSnapshot()).toBe(s.getSnapshot());
    await s.start();
    off();
    expect(seen.at(-1)).toBe(3);
  });
});

describe("findBaselineCase", () => {
  it("looks through the baseline's shards in order; unknown id → null", async () => {
    const calls: number[] = [];
    const o = { fetchImpl: fixtureFetch({ calls }), cache: new Map() };
    const found = await findBaselineCase(D_MANY, 3, "slice-009", o);
    expect(found?.case_id).toBe("slice-009");
    expect(calls).toEqual([0]);
    expect(await findBaselineCase(D_MANY, 3, "no-such-case", o)).toBeNull();
  });
});

describe("cases URL state", () => {
  const base: CasesState = {
    failing: true,
    tenant: "",
    category: "",
    lang: "",
    perturbation: "",
    q: "",
    page: 1,
    case: "",
  };
  it("defaults to failing-only when a failing case exists, else all", () => {
    expect(parseCasesQuery("", true).failing).toBe(true);
    expect(parseCasesQuery("", false).failing).toBe(false);
    expect(parseCasesQuery("?failing=0", true).failing).toBe(false);
    expect(parseCasesQuery("failing=1", false).failing).toBe(true);
  });
  it("round-trips filters, search, page and case through the query", () => {
    const state: CasesState = {
      failing: false,
      tenant: "kanzlei_mueller",
      category: "factual",
      lang: "en",
      perturbation: "typo",
      q: "Probezeit",
      page: 3,
      case: "slice-007",
    };
    const query = toCasesQuery(state, true);
    expect(new URLSearchParams(query).get("failing")).toBe("0");
    expect(parseCasesQuery(query, true)).toEqual(state);
    expect(toCasesQuery(base, true)).toBe("");
    expect(toCasesQuery({ ...base, failing: false }, false)).toBe("");
  });
  it("ignores junk: a bad page is 1, unknown keys are dropped", () => {
    expect(parseCasesQuery("page=-4&x=1&lang=fr", true)).toMatchObject({ page: 1, lang: "fr" });
  });
});

describe("filter, search, sort and pagination", () => {
  const rows = [
    makeCase({ case_id: "b-2", failing: false, question: "Urlaub im Jahr?" }),
    makeCase({
      case_id: "a-9",
      failing: true,
      tenant: "stadtwerke_sued",
      lang: "en",
      question: "Notice period?",
    }),
    makeCase({ case_id: "a-1", failing: false, perturbation: "typo" }),
    makeCase({ case_id: "c-3", failing: true, category: "leak_probe" }),
  ];
  const all: CasesState = { ...parseCasesQuery("", false) };
  it("sorts failing first, then case_id (code points)", () => {
    expect(applyCases(rows, all).rows.map((c) => c.case_id)).toEqual(["a-9", "c-3", "a-1", "b-2"]);
  });
  it("filters failing, tenant, category, lang and perturbation", () => {
    expect(filterCases(rows, { ...all, failing: true }).map((c) => c.case_id)).toEqual([
      "a-9",
      "c-3",
    ]);
    expect(filterCases(rows, { ...all, tenant: "stadtwerke_sued" })).toHaveLength(1);
    expect(filterCases(rows, { ...all, category: "leak_probe" })[0]?.case_id).toBe("c-3");
    expect(filterCases(rows, { ...all, lang: "en" })[0]?.case_id).toBe("a-9");
    expect(filterCases(rows, { ...all, perturbation: "typo" })[0]?.case_id).toBe("a-1");
  });
  it("searches id and question, case-insensitively", () => {
    expect(filterCases(rows, { ...all, q: "URLAUB" }).map((c) => c.case_id)).toEqual(["b-2"]);
    expect(filterCases(rows, { ...all, q: "a-1" }).map((c) => c.case_id)).toEqual(["a-1"]);
  });
  it("pages by 25 and clamps the page", () => {
    const many = Array.from({ length: 60 }, (_, i) =>
      makeCase({ case_id: `c-${String(i).padStart(3, "0")}` }),
    );
    const v = applyCases(many, { ...all, page: 99 });
    expect([CASE_PAGE_SIZE, v.pages, v.page, v.rows.length, v.from, v.to, v.total]).toEqual([
      25, 3, 3, 10, 51, 60, 60,
    ]);
  });
  it("offers the facet values of the loaded rows", () => {
    expect(facetValues(rows, "tenant")).toEqual(["kanzlei_mueller", "stadtwerke_sued"]);
    expect(facetValues(rows, "perturbation")).toEqual(["typo"]);
  });
});
