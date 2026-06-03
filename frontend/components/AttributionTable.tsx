"use client";

import { PageState, titleize } from "@/components/viewPrimitives";
import { usd } from "@/lib/format";

type AttributionRow = {
  actions: number;
  gross_savings_usd?: string | number | null;
  lever: string | null;
  measurement_method: string;
  net_savings_usd: string | number | null;
};

function money(value: string | number | null | undefined): string {
  return value === null || value === undefined ? "-" : usd(value, 0);
}

export function AttributionTable({
  empty,
  emptyDetail,
  rows,
  showGross = false,
}: {
  empty: string;
  emptyDetail: string;
  rows: AttributionRow[];
  showGross?: boolean;
}) {
  if (rows.length === 0) {
    return <PageState empty={empty} emptyDetail={emptyDetail} />;
  }
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Lever</th>
          <th>Method</th>
          <th className="r">Actions</th>
          {showGross ? <th className="r">Gross saved</th> : null}
          <th className="r">Net saved</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.lever}-${row.measurement_method}`}>
            <td>{row.lever ? titleize(row.lever) : "General"}</td>
            <td className="muted">{titleize(row.measurement_method)}</td>
            <td className="r">{row.actions}</td>
            {showGross ? <td className="r">{money(row.gross_savings_usd)}</td> : null}
            <td className="r">{money(row.net_savings_usd)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
