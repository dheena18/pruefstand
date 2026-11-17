/** The Try-it state machine (ui-spec §4.6): a pure reducer, no timers and no network. */

export const MAX_QUESTION = 500;
export const SLOW_AFTER_S = 10;

export type TryStateId =
  | "T-IDLE"
  | "T-INVALID"
  | "T-LOADING"
  | "T-SLOW"
  | "T-TIMEOUT"
  | "T-CANCELLED"
  | "T-SUCCESS"
  | "T-REFUSED"
  | "T-RATE-LIMITED"
  | "T-BUSY"
  | "T-DAILY-LIMIT"
  | "T-BUDGET"
  | "T-DEMO-OFF"
  | "T-REJECTED"
  | "T-NETWORK"
  | "T-SERVER-ERROR";

export interface AnswerChunk {
  chunk_id: string;
  doc_id: string;
  tenant_id: string | null;
  text: string;
  score: number;
  rank: number;
  used_in_prompt: boolean | null;
}

export interface Answer {
  answer: string;
  citations: string[];
  chunks: AnswerChunk[];
  refused: boolean;
  model: string | null;
}

export interface Failure {
  state: TryStateId;
  retryAfterS: number | null;
}

export interface TryState {
  id: TryStateId;
  tenant: string;
  question: string;
  /** True after the first input or a submit: validation messages may show (never on blur). */
  touched: boolean;
  elapsedS: number;
  countdownS: number | null;
  /** Ask stays disabled for the page session (daily limit, budget). */
  locked: boolean;
  answer: Answer | null;
}

export type TryAction =
  | { type: "input"; question: string }
  | { type: "tenant"; tenant: string }
  | { type: "submit" }
  | { type: "tick" }
  | { type: "countdown" }
  | { type: "answered"; answer: Answer }
  | { type: "failed"; failure: Failure }
  | { type: "cancel" }
  | { type: "client_timeout" };

export function initialState(tenant: string): TryState {
  return {
    id: "T-IDLE",
    tenant,
    question: "",
    touched: false,
    elapsedS: 0,
    countdownS: null,
    locked: false,
    answer: null,
  };
}

/** `empty` or `too_long` when the question cannot be sent, else null. */
export function validate(question: string): "empty" | "too_long" | null {
  if (question.trim() === "") return "empty";
  return question.length > MAX_QUESTION ? "too_long" : null;
}

const CODES: Record<string, TryStateId> = {
  rate_limited: "T-RATE-LIMITED",
  busy: "T-BUSY",
  daily_limit: "T-DAILY-LIMIT",
  budget_exhausted: "T-BUDGET",
  demo_disabled: "T-DEMO-OFF",
  invalid_request: "T-REJECTED",
  body_too_large: "T-REJECTED",
  timeout: "T-TIMEOUT",
};

/** Map an error answer to a state: the `code` of the JSON body, else by status (4xx rejected, 5xx server). */
export function classify(status: number, body: unknown): Failure {
  const record = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const code = typeof record["code"] === "string" ? record["code"] : "";
  const retry = record["retry_after_s"];
  const retryAfterS = typeof retry === "number" && retry > 0 ? Math.ceil(retry) : null;
  const known = CODES[code];
  if (known !== undefined) return { state: known, retryAfterS };
  return { state: status >= 500 ? "T-SERVER-ERROR" : "T-REJECTED", retryAfterS: null };
}

export function isLoading(id: TryStateId): boolean {
  return id === "T-LOADING" || id === "T-SLOW";
}

/** The question can be submitted now. */
export function canAsk(state: TryState): boolean {
  if (state.locked || isLoading(state.id) || validate(state.question) !== null) return false;
  return state.countdownS === null || state.countdownS <= 0;
}

function clearedCountdown(state: TryState): TryState {
  return state.countdownS === null ? state : { ...state, countdownS: null };
}

export function reduce(state: TryState, action: TryAction): TryState {
  switch (action.type) {
    case "input": {
      if (isLoading(state.id)) return state; // inputs are read-only while loading
      const question = action.question.slice(0, MAX_QUESTION);
      const invalid = validate(question) !== null;
      const next = { ...state, question, touched: true };
      if (invalid) return { ...next, id: "T-INVALID" };
      return { ...next, id: state.id === "T-INVALID" ? "T-IDLE" : state.id };
    }
    case "tenant":
      return isLoading(state.id) ? state : { ...state, tenant: action.tenant };
    case "submit": {
      if (isLoading(state.id)) return state; // double-submit guard
      if (!canAsk(state)) {
        return validate(state.question) === null
          ? state
          : { ...state, id: "T-INVALID", touched: true };
      }
      return {
        ...clearedCountdown(state),
        id: "T-LOADING",
        elapsedS: 0,
        answer: null,
        touched: true,
      };
    }
    case "tick": {
      if (!isLoading(state.id)) return state;
      const elapsedS = state.elapsedS + 1;
      return { ...state, elapsedS, id: elapsedS >= SLOW_AFTER_S ? "T-SLOW" : "T-LOADING" };
    }
    case "countdown":
      if (state.countdownS === null) return state;
      return { ...state, countdownS: Math.max(0, state.countdownS - 1) };
    case "answered":
      return {
        ...state,
        id: action.answer.refused ? "T-REFUSED" : "T-SUCCESS",
        answer: action.answer,
        countdownS: null,
      };
    case "failed": {
      const { state: id, retryAfterS } = action.failure;
      const countdown = id === "T-RATE-LIMITED" || id === "T-BUSY";
      return {
        ...state,
        id,
        answer: null,
        countdownS: countdown ? retryAfterS : null,
        locked: state.locked || id === "T-DAILY-LIMIT" || id === "T-BUDGET",
      };
    }
    case "cancel":
      return isLoading(state.id) ? { ...state, id: "T-CANCELLED", answer: null } : state;
    case "client_timeout":
      return isLoading(state.id) ? { ...state, id: "T-TIMEOUT", answer: null } : state;
  }
}
