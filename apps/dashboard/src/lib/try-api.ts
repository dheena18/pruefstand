/** The one network call of the Try-it page: `POST <demo>/v1/query` (interfaces §16, D138). */

import { classify, type Answer, type AnswerChunk, type Failure } from "./try-state";

export type Outcome =
  { kind: "ok"; answer: Answer } | { kind: "failure"; failure: Failure } | { kind: "aborted" };

function isChunk(value: unknown): value is AnswerChunk {
  const c = value as Partial<AnswerChunk> | null;
  return (
    typeof c?.chunk_id === "string" && typeof c.doc_id === "string" && typeof c.text === "string"
  );
}

/** Parse a 200 body; `null` when it does not look like a query answer. */
export function parseAnswer(body: unknown): Answer | null {
  const b = body as Record<string, unknown> | null;
  if (typeof b !== "object" || b === null || typeof b["answer"] !== "string") return null;
  const citations = Array.isArray(b["citations"])
    ? b["citations"].filter((c) => typeof c === "string")
    : [];
  const chunks = Array.isArray(b["chunks"]) ? b["chunks"].filter(isChunk) : [];
  return {
    answer: b["answer"],
    citations,
    chunks: chunks.map((c) => ({
      ...c,
      tenant_id: c.tenant_id ?? null,
      used_in_prompt: c.used_in_prompt ?? null,
    })),
    refused: b["refused"] === true,
    model: typeof b["model"] === "string" ? b["model"] : null,
  };
}

/**
 * Ask the demo API. An abort by the caller is `aborted`; a fetch that throws (offline, CORS, DNS)
 * is the `T-NETWORK` failure; any other answer goes through `classify` or `parseAnswer`.
 */
export async function ask(
  baseUrl: string,
  tenant: string,
  question: string,
  signal: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<Outcome> {
  let response: Response;
  try {
    response = await fetcher(`${baseUrl}/v1/query`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, question }),
      signal,
    });
  } catch {
    if (signal.aborted) return { kind: "aborted" };
    return { kind: "failure", failure: { state: "T-NETWORK", retryAfterS: null } };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null; // a non-JSON body is a server error (5xx) or a rejection (4xx) by status
  }
  if (response.ok) {
    const answer = parseAnswer(body);
    if (answer !== null) return { kind: "ok", answer };
    return { kind: "failure", failure: { state: "T-SERVER-ERROR", retryAfterS: null } };
  }
  return { kind: "failure", failure: classify(response.status, body) };
}
