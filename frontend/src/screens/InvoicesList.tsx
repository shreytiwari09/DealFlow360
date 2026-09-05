/** Screen 12 — Invoices List. FRONTEND.md Section 5, PRD B7. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { BillingScheduleRow } from "../lib/api";
import { dateTime, humanise, money } from "../lib/format";
import { EmptyState, ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function InvoicesList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<BillingScheduleRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<BillingScheduleRow[]>("/billing/invoices"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load invoices.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !rows) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Invoices"
        subtitle="Every one-time invoice, recurring instalment and credit note, across every order."
      />

      {!rows && <TableSkeleton rows={4} cols={6} />}

      {rows && rows.length === 0 && (
        <EmptyState
          title="No invoices yet"
          hint="A billing row appears here once an order is confirmed."
        />
      )}

      {rows && rows.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Type</th>
                  <th className="num">Amount</th>
                  <th>Due date</th>
                  <th>Status</th>
                  <th>Invoice #</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="clickable" onClick={() => navigate(`/invoices/${row.id}`)}>
                    <td className="primary-cell">{row.quote_number}</td>
                    <td>
                      {humanise(row.schedule_type)}
                      {row.is_credit_note && (
                        <span className="badge badge--accent" style={{ marginLeft: 8 }}>
                          Credit note
                        </span>
                      )}
                    </td>
                    <td className="num mono-num">{money(row.amount)}</td>
                    <td>{dateTime(row.due_date)}</td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="sub-cell">{row.invoice_number ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "var(--space-3)" }}>
            <NoteBar>Click a row to open its invoice detail and record a payment.</NoteBar>
          </div>
        </div>
      )}
    </>
  );
}
