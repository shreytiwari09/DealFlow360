/**
 * Screen 8 — Fulfillment Detail. FRONTEND.md Section 5.
 *
 * Viewing this screen for a confirmed order auto-generates the suggested
 * split on the backend the first time it is opened — there is nothing to
 * "compute" here on purpose, matching PRD B6's "the system suggests a
 * warehouse fulfillment split".
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { FulfillmentDetail as Detail, FulfillmentOverview } from "../lib/api";
import { money, points } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

interface OverrideRow {
  quotation_line_id: number;
  product_name: string;
  warehouse_id: number;
  quantity: string;
}

export default function FulfillmentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [overview, setOverview] = useState<FulfillmentOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [draft, setDraft] = useState<OverrideRow[]>([]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [d, o] = await Promise.all([
        api.get<Detail>(`/fulfillment/${id}`),
        api.get<FulfillmentOverview>("/fulfillment"),
      ]);
      setDetail(d);
      setOverview(o);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this fulfillment.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  function startOverride() {
    if (!detail) return;
    setDraft(
      detail.splits.map((split) => ({
        quotation_line_id: split.quotation_line_id,
        product_name: split.product_name,
        warehouse_id: split.warehouse_id,
        quantity: split.quantity,
      })),
    );
    setOverriding(true);
  }

  // Warehouses that stock each product on this order, with live availability
  // shown, so the override picker is informed rather than a blind text field.
  const warehousesByProduct = useMemo(() => {
    if (!overview) return new Map<string, { warehouse_id: number; warehouse_name: string; available: string }[]>();
    const map = new Map<string, { warehouse_id: number; warehouse_name: string; available: string }[]>();
    for (const row of overview.stock) {
      const list = map.get(row.product_name) ?? [];
      list.push({ warehouse_id: row.warehouse_id, warehouse_name: row.warehouse_name, available: row.available });
      map.set(row.product_name, list);
    }
    return map;
  }, [overview]);

  function addOverrideRow(lineId: number, productName: string) {
    const options = warehousesByProduct.get(productName) ?? [];
    const unused = options.find((o) => !draft.some((d) => d.quotation_line_id === lineId && d.warehouse_id === o.warehouse_id));
    if (!unused) return;
    setDraft((current) => [
      ...current,
      { quotation_line_id: lineId, product_name: productName, warehouse_id: unused.warehouse_id, quantity: "0" },
    ]);
  }

  async function saveOverride() {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const lines = draft
        .filter((row) => Number(row.quantity) > 0)
        .map((row) => ({
          quotation_line_id: row.quotation_line_id,
          warehouse_id: row.warehouse_id,
          quantity: Number(row.quantity),
        }));
      const updated = await api.post<Detail>(`/fulfillment/${id}/override`, { lines });
      setDetail(updated);
      setOverriding(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the override.");
    } finally {
      setBusy(false);
    }
  }

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.post<Detail>(`/fulfillment/${id}/accept`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept the split.");
    } finally {
      setBusy(false);
    }
  }

  async function consolidate(backorderId: number) {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.post<Detail>(`/fulfillment/${id}/backorders/${backorderId}/consolidate`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Not enough stock to consolidate yet.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!detail) return <TableSkeleton rows={4} cols={4} />;

  // Lines that still have room for another warehouse allocation in override mode.
  const linesById = new Map(detail.splits.map((s) => [s.quotation_line_id, s.product_name]));
  for (const b of detail.backorders) linesById.set(b.quotation_line_id, b.product_name);
  const openBackorders = detail.backorders.filter((b) => b.status === "open");

  return (
    <>
      <PageHeader
        title={`${detail.quote_number} · ${detail.customer_name}`}
        subtitle="Opened by clicking a row on the Fulfillment List."
        actions={
          <>
            <StatusBadge status={detail.status} />
            <button className="btn" onClick={() => navigate(`/quotations/${detail.quotation_id}`)}>
              Open quotation
            </button>
          </>
        }
      />

      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="stack">
        <div className="grid-3">
          <div className="card">
            <div className="kpi__label">Shipments</div>
            <div className="kpi__value">{detail.shipment_count}</div>
          </div>
          <div className="card">
            <div className="kpi__label">Estimated cost</div>
            <div className="kpi__value">{money(detail.estimated_shipping_cost)}</div>
          </div>
          <div className="card">
            <div className="kpi__label">Backorders</div>
            <div className="kpi__value">{openBackorders.length}</div>
          </div>
        </div>

        <div className="card">
          <div className="row row--between" style={{ marginBottom: "var(--space-3)" }}>
            <h2 className="card__title" style={{ margin: 0 }}>
              Warehouse split
            </h2>
            {detail.can_act && detail.status === "pending" && !overriding && (
              <div className="row">
                <button className="btn btn--primary" disabled={busy} onClick={() => void accept()}>
                  Accept Suggested Split
                </button>
                <button className="btn" disabled={busy} onClick={startOverride}>
                  Manual Override
                </button>
              </div>
            )}
            {overriding && (
              <div className="row">
                <button className="btn btn--primary" disabled={busy} onClick={() => void saveOverride()}>
                  Save Override
                </button>
                <button className="btn" onClick={() => setOverriding(false)}>
                  Cancel
                </button>
              </div>
            )}
          </div>

          {!overriding && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Warehouse</th>
                    <th>Product</th>
                    <th className="num">Qty Fulfilled</th>
                    <th className="num">Est. Shipments</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.splits.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted" style={{ textAlign: "center" }}>
                        Nothing could be allocated from any warehouse.
                      </td>
                    </tr>
                  )}
                  {detail.splits.map((split, index) => (
                    <tr key={index}>
                      <td className="primary-cell">
                        {split.warehouse_name}
                        {split.is_manual_override && (
                          <span className="badge badge--accent" style={{ marginLeft: 8 }}>
                            Manual
                          </span>
                        )}
                      </td>
                      <td>{split.product_name}</td>
                      <td className="num mono-num">{Number(split.quantity)} units</td>
                      <td className="num mono-num">1</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {overriding && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Warehouse</th>
                    <th className="num">Quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.map((row, index) => {
                    const options = warehousesByProduct.get(row.product_name) ?? [];
                    return (
                      <tr key={index}>
                        <td>{row.product_name}</td>
                        <td>
                          <select
                            className="select"
                            value={row.warehouse_id}
                            onChange={(e) => {
                              const warehouse_id = Number(e.target.value);
                              setDraft((current) =>
                                current.map((r, i) => (i === index ? { ...r, warehouse_id } : r)),
                              );
                            }}
                          >
                            {options.map((o) => (
                              <option key={o.warehouse_id} value={o.warehouse_id}>
                                {o.warehouse_name} ({Number(o.available)} available)
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="num">
                          <input
                            className="input input--num"
                            type="number"
                            min="0"
                            value={row.quantity}
                            onChange={(e) => {
                              const quantity = e.target.value;
                              setDraft((current) =>
                                current.map((r, i) => (i === index ? { ...r, quantity } : r)),
                              );
                            }}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ marginTop: "var(--space-2)" }}>
                {[...linesById.entries()].map(([lineId, productName]) => (
                  <button
                    key={lineId}
                    className="btn btn--sm"
                    style={{ marginRight: 8 }}
                    onClick={() => addOverrideRow(lineId, productName)}
                  >
                    + Add warehouse for {productName}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {detail.backorders.length > 0 && (
          <div className="card">
            <h2 className="card__title">Backorders</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="num">Outstanding</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {detail.backorders.map((b) => (
                    <tr key={b.id}>
                      <td className="primary-cell">{b.product_name}</td>
                      <td className="num mono-num">{points(b.quantity_outstanding)}</td>
                      <td>
                        <StatusBadge status={b.status} />
                      </td>
                      <td>
                        {b.status === "open" && detail.can_act && (
                          <button className="btn btn--sm" disabled={busy} onClick={() => void consolidate(b.id)}>
                            Consolidate
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {openBackorders.length > 0 && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <NoteBar tone="warning">
                  A "Consolidate Remaining Backorder" prompt appears automatically once stock
                  arrives — here, click Consolidate to check whether enough stock now exists.
                </NoteBar>
              </div>
            )}
          </div>
        )}

        {!detail.can_act && detail.status === "pending" && (
          <NoteBar>
            You can review this split, but only Finance/Operations can accept or override it.
          </NoteBar>
        )}
      </div>
    </>
  );
}
