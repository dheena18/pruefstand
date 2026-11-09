/** An id that is safe to put in a URL path and a file name (run ids, case ids); `_empty` never matches. */
export const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** Placeholder segment of an empty dynamic route (ui-spec §2.1, Y7.2); never linked, `noindex`. */
export const EMPTY_ID = "_empty";

export const isSafeId = (value: string): boolean => SAFE_ID.test(value);
