// All matrix rows per fixture set (T8.4 appends its Try-it rows here).
import type { Row, SetName } from "./matrix";
import { emptyRows } from "./matrix-empty";
import { caseRows } from "./matrix-cases";
import { populatedRows } from "./matrix-populated";
import { tier2Rows } from "./matrix-tier2";

export const rowsOf = (set: SetName): Row[] =>
  set === "populated" ? [...populatedRows, ...caseRows, ...tier2Rows] : emptyRows;
