/** Screen 7 — Fulfillment List. FRONTEND.md Section 5. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { FulfillmentOverview } from "../lib/api";
import { EmptyState, ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function FulfillmentList() {
  const navigate = useNavigate();
  const [data, setData] = useState<FulfillmentOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.get<FulfillmentOverview>("/fulfillment"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load fulfillment data.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !data) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Fulfillment"
        subtitle="Live stock per warehouse, plus every order that still needs fulfilling."
      />

      <div className="stack">
        <div className="card">
          <h2 className="card__title">Stock by warehouse</h2>
          {!data && <TableSkeleton rows={4} cols={5} />}
          {data && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Warehouse</th>
                    <th>Product</th>
                    <th className="num">In Stock</th>
                    <th className="num">Reserved</th>
                    <th className="num">Available</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stock.map((row) => (
                    <tr key={`${row.warehouse_id}-${row.product_id}`}>
                      <td>{row.warehouse_name}</td>
                      <td className="primary-cell">{row.product_name}</td>
                      <td className="num mono-num">{Number(row.quantity_on_hand)}</td>
                      <td className="num mono-num">{Number(row.quantity_reserved)}</td>
                      <td className="num mono-num">
                        <strong>{Number(row.available)}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="card__title">Orders awaiting fulfillment</h2>
          {!data && <TableSkeleton rows={3} cols={4} />}
          {data && data.orders.length === 0 && (
            <EmptyState
              title="Nothing waiting"
              hint="Orders appear here once a quotation has been confirmed."
            />
          )}
          {data && data.orders.length > 0 && (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Customer</th>
                      <th>Status</th>
                      <th>Warehouse</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.map((order) => (
                      <tr
                        key={order.quotation_id}
                        className="clickable"
                        onClick={() => navigate(`/fulfillment/${order.quotation_id}`)}
                      >
                        <td className="primary-cell">{order.quote_number}</td>
                        <td>{order.customer_name}</td>
                        <td>
                          {order.fulfillment_status ? (
                            <StatusBadge status={order.fulfillment_status} />
                          ) : (
                            <span className="badge badge--neutral">Not yet split</span>
                          )}
                        </td>
                        <td className="sub-cell">
                          {order.warehouse_names.length > 0
                            ? order.warehouse_names.join(" + ")
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ marginTop: "var(--space-3)" }}>
                <NoteBar>Click an order row to open its warehouse split detail.</NoteBar>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
