// Empty-set rows of the ui-spec §14.2 matrix.
import { NOT_FOUND, row, type Row } from "./matrix";

export const emptyRows: Row[] = [
  row({
    page: "Root redirect",
    state: "root",
    set: "empty",
    path: "/",
    lang: "de",
    expect: { redirectTo: "/de/" },
  }),
  row({
    page: "Runs list",
    state: "L-EMPTY",
    set: "empty",
    path: "/{l}/",
    expect: { keys: ["empty.runs"], states: ["L-EMPTY"] },
  }),
  ...["", "diff/", "slices/", "cases/"].map((tail) =>
    row({
      page: "Placeholder",
      state: `E-PLACEHOLDER (${tail || "summary"})`,
      set: "empty",
      path: `/{l}/runs/_empty/${tail}`,
      expect: { keys: ["empty.runs"], noindex: true },
    }),
  ),
  row({
    page: "Licences",
    state: "default",
    set: "empty",
    path: "/{l}/licences/",
    expect: { keys: ["licences.title"] },
  }),
  row({
    page: "404",
    state: "X-404 unknown run",
    set: "empty",
    path: "/de/runs/does-not-exist/",
    status: 404,
    lang: "de",
    expect: NOT_FOUND,
  }),
  row({
    page: "404",
    state: "X-404 unknown locale",
    set: "empty",
    path: "/fr/",
    status: 404,
    lang: "de",
    expect: NOT_FOUND,
  }),
];
