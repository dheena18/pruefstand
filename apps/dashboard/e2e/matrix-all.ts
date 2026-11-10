// All matrix rows per fixture set (T8.4 appends its Try-it rows here).
import type { Row, SetName } from "./matrix";
import { emptyRows } from "./matrix-empty";
import { populatedRows } from "./matrix-populated";

export const rowsOf = (set: SetName): Row[] => (set === "populated" ? populatedRows : emptyRows);
