// The page x state matrix of ui-spec §14.2 (rows that run in the PR projects). Each row runs in
// {light, dark} x {de, en} per project, i.e. 4 combinations per project; `report.html` rows run in
// {light, dark} (English only). T8.4 appends the Try-it rows with the same shape.

export type SetName = "populated" | "empty";

export interface Expect {
  /** i18n keys whose text (placeholders as wildcards) must be visible in the page, in the row's locale. */
  keys?: string[];
  /** Literal words (status words) that must be visible, locale-independent. */
  words?: string[];
  /** `data-state` values that must be present. */
  states?: string[];
  /** `data-state` values that must be absent. */
  absentStates?: string[];
  /** CSS selectors that must have no match. */
  absent?: string[];
  /** Query-driven page: wait for `main[data-hydrated]` first (ui-spec §6). */
  hydrated?: boolean;
  /** Static root document: follow the meta refresh and expect to end on this path. */
  redirectTo?: string;
  /** `<meta name="robots" content="noindex">` present. */
  noindex?: boolean;
}

export interface Row {
  page: string;
  state: string;
  set: SetName;
  fixtureRunId: string | null;
  /** Path with `{l}` for the locale; relative to the set's base URL. */
  path: string;
  /** HTTP status of the document (404 pages answer 404). */
  status: number;
  /** `<html lang>`: the locale, or `de` for documents that are not localised (root, site 404). */
  lang: "locale" | "de";
  kind: "page" | "report";
  expect: Expect;
}

export const row = (r: Partial<Row> & Pick<Row, "page" | "state" | "set" | "path">): Row => ({
  fixtureRunId: null,
  status: 200,
  lang: "locale",
  kind: "page",
  expect: {},
  ...r,
});

export const NOT_FOUND: Expect = { keys: ["notfound.title"] };
export const run = (id: string) => `/{l}/runs/${id}/`;
