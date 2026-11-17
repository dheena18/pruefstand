import { describe, expect, it } from "vitest";

import { ask, parseAnswer } from "@/lib/try-api";

const OK = {
  answer: "Vier Wochen (§ 622 BGB).",
  citations: ["§ 622 BGB", 7],
  chunks: [
    {
      chunk_id: "c1",
      doc_id: "d1",
      tenant_id: "shared_public",
      text: "t",
      score: 0.8,
      rank: 1,
      used_in_prompt: false,
    },
    { chunk_id: "c2", doc_id: "d2", text: "u", score: 0.5, rank: 2 },
    { nonsense: true },
  ],
  refused: false,
  model: "qwen",
};
const json = (status: number, body: unknown) =>
  (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
const signal = () => new AbortController().signal;

describe("parseAnswer", () => {
  it("keeps well-formed citations and chunks and fills the optional fields", () => {
    const a = parseAnswer(OK);
    expect(a?.citations).toEqual(["§ 622 BGB"]);
    expect(a?.chunks.map((c) => [c.chunk_id, c.tenant_id, c.used_in_prompt])).toEqual([
      ["c1", "shared_public", false],
      ["c2", null, null],
    ]);
    expect(a?.refused).toBe(false);
  });
  it("is null without an answer string", () => {
    expect(parseAnswer({})).toBeNull();
    expect(parseAnswer(null)).toBeNull();
    expect(parseAnswer("x")).toBeNull();
  });
});

describe("ask", () => {
  it("returns the parsed answer for a 200 and posts the tenant and the question", async () => {
    let seen: { url: string; init: RequestInit | undefined } | null = null;
    const fetcher = (async (url: string, init?: RequestInit) => {
      seen = { url, init };
      return new Response(JSON.stringify(OK), { status: 200 });
    }) as typeof fetch;
    const out = await ask("https://demo.example", "kanzlei_mueller", "Frage?", signal(), fetcher);
    expect(out.kind).toBe("ok");
    expect(seen).not.toBeNull();
    expect((seen as unknown as { url: string }).url).toBe("https://demo.example/v1/query");
    expect(JSON.parse(String((seen as unknown as { init: RequestInit }).init.body))).toEqual({
      tenant_id: "kanzlei_mueller",
      question: "Frage?",
    });
  });
  it("maps an error body by its code", async () => {
    const out = await ask(
      "u",
      "t",
      "q",
      signal(),
      json(429, { code: "rate_limited", message: "m", retry_after_s: 4 }),
    );
    expect(out).toEqual({ kind: "failure", failure: { state: "T-RATE-LIMITED", retryAfterS: 4 } });
  });
  it("a non-JSON error body is a server error or a rejection by status", async () => {
    const html = (status: number) =>
      (async () => new Response("<html>", { status })) as typeof fetch;
    expect(await ask("u", "t", "q", signal(), html(502))).toMatchObject({
      failure: { state: "T-SERVER-ERROR" },
    });
    expect(await ask("u", "t", "q", signal(), html(400))).toMatchObject({
      failure: { state: "T-REJECTED" },
    });
  });
  it("a 200 that is not an answer is a server error", async () => {
    expect(await ask("u", "t", "q", signal(), json(200, { nope: 1 }))).toMatchObject({
      failure: { state: "T-SERVER-ERROR" },
    });
  });
  it("a throwing fetch is T-NETWORK; an aborted one is aborted", async () => {
    const down = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    expect(await ask("u", "t", "q", signal(), down)).toMatchObject({
      failure: { state: "T-NETWORK" },
    });
    const controller = new AbortController();
    controller.abort();
    expect(await ask("u", "t", "q", controller.signal, down)).toEqual({ kind: "aborted" });
  });
});
