import type { ReactNode } from "react";

export interface Column<T> {
  id: string;
  header: string;
  /** Visually hidden explanation of the column (e.g. `runs.tier_help`). */
  help?: string;
  /** When set, the header is a sort `<button>` with `aria-sort`. */
  sortKey?: string;
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

export interface DataTableProps<T> {
  /** Accessible name of the scroll region and the table. */
  label: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Card layout of one row, shown below 640 px (UI-23). */
  card: (row: T) => ReactNode;
  sort?: { key: string; dir: "asc" | "desc" } | undefined;
  onSort?: ((key: string) => void) | undefined;
}

function Header<T>({
  col,
  sort,
  onSort,
}: { col: Column<T> } & Pick<DataTableProps<T>, "sort" | "onSort">) {
  const content = (
    <>
      {col.header}
      {col.help === undefined ? null : <span className="sr-only"> ({col.help})</span>}
    </>
  );
  const sorted = col.sortKey !== undefined && sort?.key === col.sortKey;
  const ariaSort = sorted ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
  return (
    <th
      scope="col"
      className={col.numeric === true ? "num" : undefined}
      aria-sort={col.sortKey === undefined ? undefined : ariaSort}
    >
      {col.sortKey === undefined ? (
        content
      ) : (
        <button type="button" className="sort-btn" onClick={() => onSort?.(col.sortKey ?? "")}>
          {content}
          <span aria-hidden="true">{sorted ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}</span>
        </button>
      )}
    </th>
  );
}

/**
 * Responsive list (ui-spec §5, UI-23): a table in a focusable, labelled scroll region from 640 px, one card per
 * row below (the stylesheet shows one of the two). Only this region scrolls horizontally.
 */
export function DataTable<T>({
  label,
  columns,
  rows,
  rowKey,
  card,
  sort,
  onSort,
}: DataTableProps<T>) {
  return (
    <>
      <div className="table-wrap data-table__table" role="region" aria-label={label} tabIndex={0}>
        <table className="data">
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr>
              {columns.map((col) => (
                <Header key={col.id} col={col} sort={sort} onSort={onSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((col) => (
                  <td key={col.id} className={col.numeric === true ? "num" : undefined}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="data-table__cards" aria-label={label}>
        {rows.map((row) => (
          <li key={rowKey(row)} className="card">
            {card(row)}
          </li>
        ))}
      </ul>
    </>
  );
}
