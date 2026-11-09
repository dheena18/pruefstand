import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DataTable, type Column } from "@/components/DataTable";

interface Row {
  id: string;
  n: number;
}
const columns: Column<Row>[] = [
  { id: "id", header: "Id", sortKey: "id", render: (r) => r.id },
  { id: "n", header: "N", numeric: true, help: "count", render: (r) => r.n },
];
const rows: Row[] = [
  { id: "a", n: 1 },
  { id: "b", n: 2 },
];

describe("DataTable", () => {
  it("has aria-sort on sortable headers and a sort button", () => {
    const onSort = vi.fn();
    render(
      <DataTable
        label="Runs"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        card={(r) => r.id}
        sort={{ key: "id", dir: "desc" }}
        onSort={onSort}
      />,
    );
    const header = screen.getByRole("columnheader", { name: /Id/ });
    expect(header).toHaveAttribute("aria-sort", "descending");
    fireEvent.click(screen.getByRole("button", { name: /Id/ }));
    expect(onSort).toHaveBeenCalledWith("id");
    expect(screen.getByRole("columnheader", { name: /N/ })).not.toHaveAttribute("aria-sort");
  });
  it("puts the table in a focusable, labelled scroll region and renders cards for narrow screens", () => {
    const { container } = render(
      <DataTable
        label="Runs"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        card={(r) => <b>{r.id}</b>}
      />,
    );
    const region = screen.getByRole("region", { name: "Runs" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(container.querySelectorAll(".data-table__cards > li")).toHaveLength(2);
    expect(screen.getByText("(count)")).toHaveClass("sr-only");
  });
  it("marks an unsorted sortable column aria-sort=none", () => {
    render(
      <DataTable
        label="Runs"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        card={(r) => r.id}
        sort={{ key: "other", dir: "asc" }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: /Id/ })).toHaveAttribute("aria-sort", "none");
  });
});
