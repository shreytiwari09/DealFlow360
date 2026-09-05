/** Screen 9 — Subscriptions List. FRONTEND.md Section 5, PRD B7. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { SubscriptionSummary } from "../lib/api";
import { dateTime, money } from "../lib/format";
import { EmptyState, ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function SubscriptionsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<SubscriptionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<SubscriptionSummary[]>("/billing/subscriptions"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load subscriptions.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !rows) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Subscriptions"
        subtitle="Every recurring line, across every hybrid order, in one place."
      />

      {!rows && <TableSkeleton rows={4} cols={6} />}

      {rows && rows.length === 0 && (
        <EmptyState
          title="No subscriptions yet"
          hint="A subscription appears here once an order with a subscription line is confirmed."
        />
      )}

      {rows && rows.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Customer</th>
                  <th>Plan</th>
                  <th className="num">Qty</th>
                  <th className="num">Amount / cycle</th>
                  <th>Status</th>
                  <th>Current cycle</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="clickable"
                    onClick={() => navigate(`/subscriptions/${row.id}`)}
                  >
                    <td className="primary-cell">{row.quote_number}</td>
                    <td>{row.customer_name}</td>
                    <td>
                      {row.product_name}
                      <div className="sub-cell">{row.plan_name}</div>
                    </td>
                    <td className="num mono-num">{Number(row.quantity)}</td>
                    <td className="num mono-num">
                      {money((Number(row.quantity) * Number(row.unit_amount)).toFixed(2))}
                    </td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="sub-cell">
                      {dateTime(row.current_cycle_start)} → {dateTime(row.current_cycle_end)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "var(--space-3)" }}>
            <NoteBar>Click a subscription row to open its billing detail and proration history.</NoteBar>
          </div>
        </div>
      )}
    </>
  );
}
