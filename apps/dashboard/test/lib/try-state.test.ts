import { describe, expect, it } from "vitest";

import {
  MAX_QUESTION,
  canAsk,
  classify,
  initialState,
  reduce,
  validate,
  type Answer,
  type TryAction,
  type TryState,
} from "@/lib/try-state";

const ANSWER: Answer = {
  answer: "Vier Wochen.",
  citations: ["§ 622 BGB"],
  chunks: [],
  refused: false,
  model: "m",
};
const run = (state: TryState, ...actions: TryAction[]) => actions.reduce(reduce, state);
const typed = (q = "Welche Frist gilt?") =>
  run(initialState("kanzlei_mueller"), { type: "input", question: q });
const loading = () => run(typed(), { type: "submit" });

describe("validate", () => {
  it("rejects empty, blank and over-long questions", () => {
    expect(validate("")).toBe("empty");
    expect(validate("   ")).toBe("empty");
    expect(validate("x".repeat(MAX_QUESTION + 1))).toBe("too_long");
    expect(validate("x".repeat(MAX_QUESTION))).toBeNull();
  });
});

describe("the state machine (ui-spec 4.6)", () => {
  it("starts idle, untouched, with Ask disabled", () => {
    const s = initialState("kanzlei_mueller");
    expect([s.id, s.touched, canAsk(s)]).toEqual(["T-IDLE", false, false]);
  });
  it("typing and clearing is invalid; a valid question is idle again", () => {
    const s = run(typed(), { type: "input", question: "" });
    expect([s.id, s.touched, canAsk(s)]).toEqual(["T-INVALID", true, false]);
    expect(reduce(s, { type: "input", question: "Wieder gültig?" }).id).toBe("T-IDLE");
  });
  it("input stops at 500 characters", () => {
    expect(typed("x".repeat(600)).question).toHaveLength(MAX_QUESTION);
  });
  it("submitting an empty question is invalid, not loading", () => {
    expect(reduce(initialState("a"), { type: "submit" }).id).toBe("T-INVALID");
  });
  it("submit loads; a second submit is ignored (double-submit guard)", () => {
    const s = loading();
    expect(s.id).toBe("T-LOADING");
    expect(reduce(s, { type: "submit" })).toBe(s);
    expect(canAsk(s)).toBe(false);
  });
  it("inputs are read-only while loading", () => {
    const s = loading();
    expect(reduce(s, { type: "input", question: "anders" })).toBe(s);
    expect(reduce(s, { type: "tenant", tenant: "x" })).toBe(s);
  });
  it("is slow from the tenth second on", () => {
    let s = loading();
    for (let i = 0; i < 9; i += 1) s = reduce(s, { type: "tick" });
    expect([s.id, s.elapsedS]).toEqual(["T-LOADING", 9]);
    s = reduce(s, { type: "tick" });
    expect([s.id, s.elapsedS]).toEqual(["T-SLOW", 10]);
  });
  it("ticks outside loading change nothing", () => {
    const s = typed();
    expect(reduce(s, { type: "tick" })).toBe(s);
  });
  it("a 200 is a success, a refused one a refusal", () => {
    expect(reduce(loading(), { type: "answered", answer: ANSWER }).id).toBe("T-SUCCESS");
    // a late response after Cancel or a timeout must not resurrect the card
    const cancelled = reduce(loading(), { type: "cancel" });
    expect(reduce(cancelled, { type: "answered", answer: ANSWER })).toBe(cancelled);
    expect(
      reduce(cancelled, { type: "failed", failure: { state: "T-BUSY", retryAfterS: 3 } }),
    ).toBe(cancelled);
    const idle = initialState("kanzlei_mueller");
    expect(reduce(idle, { type: "answered", answer: ANSWER })).toBe(idle);
    expect(reduce(loading(), { type: "answered", answer: { ...ANSWER, refused: true } }).id).toBe(
      "T-REFUSED",
    );
  });
  it("cancel goes to T-CANCELLED and allows asking again", () => {
    const s = reduce(loading(), { type: "cancel" });
    expect([s.id, canAsk(s)]).toEqual(["T-CANCELLED", true]);
    expect(reduce(typed(), { type: "cancel" }).id).toBe("T-IDLE");
  });
  it("a client timeout and a server timeout both end in T-TIMEOUT", () => {
    expect(reduce(loading(), { type: "client_timeout" }).id).toBe("T-TIMEOUT");
    const failed = reduce(loading(), {
      type: "failed",
      failure: classify(504, { code: "timeout", retry_after_s: null }),
    });
    expect(failed.id).toBe("T-TIMEOUT");
  });
  it("rate_limited counts down from retry_after_s and blocks Ask until 0", () => {
    let s = reduce(loading(), {
      type: "failed",
      failure: classify(429, { code: "rate_limited", retry_after_s: 2 }),
    });
    expect([s.id, s.countdownS, canAsk(s)]).toEqual(["T-RATE-LIMITED", 2, false]);
    s = run(s, { type: "countdown" }, { type: "countdown" }, { type: "countdown" });
    expect([s.countdownS, canAsk(s)]).toEqual([0, true]);
  });
  it("busy counts down too", () => {
    const s = reduce(loading(), {
      type: "failed",
      failure: classify(429, { code: "busy", retry_after_s: 5 }),
    });
    expect([s.id, s.countdownS]).toEqual(["T-BUSY", 5]);
  });
  it("daily limit and budget lock Ask for the page session", () => {
    for (const [code, id] of [
      ["daily_limit", "T-DAILY-LIMIT"],
      ["budget_exhausted", "T-BUDGET"],
    ] as const) {
      const s = reduce(loading(), {
        type: "failed",
        failure: classify(code === "daily_limit" ? 429 : 503, { code }),
      });
      expect(s.id).toBe(id);
      expect(canAsk(reduce(s, { type: "input", question: "Neue Frage?" }))).toBe(false);
    }
  });
  it("a new submit clears the countdown and the old answer", () => {
    const s = run(loading(), { type: "answered", answer: ANSWER }, { type: "submit" });
    expect([s.id, s.answer]).toEqual(["T-LOADING", null]);
  });
});

describe("classify", () => {
  it.each([
    [429, "rate_limited", "T-RATE-LIMITED"],
    [429, "busy", "T-BUSY"],
    [429, "daily_limit", "T-DAILY-LIMIT"],
    [503, "budget_exhausted", "T-BUDGET"],
    [503, "demo_disabled", "T-DEMO-OFF"],
    [422, "invalid_request", "T-REJECTED"],
    [413, "body_too_large", "T-REJECTED"],
    [504, "timeout", "T-TIMEOUT"],
  ])("%i %s -> %s", (status, code, id) => {
    expect(classify(status, { code, message: "m", retry_after_s: null }).state).toBe(id);
  });
  it("an unknown code, a non-JSON body or a bare status falls back by status class", () => {
    expect(classify(503, { code: "server_error" }).state).toBe("T-SERVER-ERROR");
    expect(classify(500, null).state).toBe("T-SERVER-ERROR");
    expect(classify(502, "<html>").state).toBe("T-SERVER-ERROR");
    expect(classify(404, { code: "new_code" }).state).toBe("T-REJECTED");
    expect(classify(400, undefined).state).toBe("T-REJECTED");
  });
  it("reads retry_after_s from the body only, rounded up, ignoring non-positive values", () => {
    expect(classify(429, { code: "rate_limited", retry_after_s: 2.2 }).retryAfterS).toBe(3);
    expect(classify(429, { code: "rate_limited", retry_after_s: 0 }).retryAfterS).toBeNull();
    expect(classify(429, { code: "rate_limited" }).retryAfterS).toBeNull();
  });
});
