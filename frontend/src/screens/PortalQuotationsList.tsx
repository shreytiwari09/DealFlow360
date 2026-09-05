/**
 * "My Quotations" — the portal shell's minimum viable list (FRONTEND.md
 * Section 2.2). Only Screen 11 itself is drawn in the wireframe; this list
 * is the smallest thing that makes the "My Quotations" nav item functional
 * for a customer with more than one quotation, reusing Screen 3's row shape
 * with customer-safe columns only.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { PortalQuotationSummary } from "../lib/api";
import { dateTime, money } from "../lib/format";
import { EmptyState, ErrorState, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function PortalQuotationsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<PortalQuotationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<PortalQuotationSummary[]>("/portal/quotations"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your quotations.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !rows) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader title="My Quotations" subtitle="Review and negotiate your quotations here." />

      {!rows && <TableSkeleton rows={3} cols={4} />}

      {rows && rows.length === 0 && (
        <EmptyState
          title="Nothing here yet"
          hint="A quotation appears here once your sales rep sends it to you."
        />
      )}

      {rows && rows.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Quotation #</th>
                  <th>Status</th>
                  <th className="num">Amount</th>
                  <th>Last Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="clickable"
                    onClick={() => navigate(`/portal/quotations/${row.id}`)}
                  >
                    <td className="primary-cell">{row.quote_number}</td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="num mono-num">{money(row.total_amount, row.currency)}</td>
                    <td className="sub-cell">{dateTime(row.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
