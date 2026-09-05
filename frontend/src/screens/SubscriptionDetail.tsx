/**
 * Screen 10 — Billing Detail. FRONTEND.md Section 5, PRD B7.
 *
 * The two-table layout is the direct UI expression of the PRD's hybrid
 * billing requirement: one-time lines and recurring lines for the SAME
 * order, shown separately. Reached by clicking a row on the Subscriptions
 * List, so the "recurring" table is that one subscription's own schedule;
 * the "one-time" table is filled in from the order's other billing rows.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { BillingScheduleRow, SubscriptionDetail as Detail, SubscriptionPlan } from "../lib/api";
import { dateTime, money } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function SubscriptionDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [oneTimeRows, setOneTimeRows] = useState<BillingScheduleRow[]>([]);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [modifying, setModifying] = useState(false);
  const [quantity, setQuantity] = useState("");
  const [planId, setPlanId] = useState<number | "">("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [d, invoices, planList] = await Promise.all([
        api.get<Detail>(`/billing/subscriptions/${id}`),
        api.get<BillingScheduleRow[]>("/billing/invoices"),
        api.get<SubscriptionPlan[]>("/subscription-plans"),
      ]);
      setDetail(d);
      setPlans(planList);
      setOneTimeRows(
        invoices.filter((row) => row.quotation_id === d.quotation_id && row.schedule_type === "one_time"),
      );
      setQuantity(d.quantity);
      setPlanId(d.plan_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this subscription.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveModify() {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const payload: { new_quantity?: number; new_plan_id?: number } = {};
      if (Number(quantity) !== Number(detail.quantity)) payload.new_quantity = Number(quantity);
      if (planId !== "" && planId !== detail.plan_id) payload.new_plan_id = planId;
      if (Object.keys(payload).length === 0) {
        setModifying(false);
        return;
      }
      const updated = await api.post<Detail>(`/billing/subscriptions/${id}/modify`, payload);
      setDetail(updated);
      setModifying(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not modify this subscription.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!detail) return;
    // PRD B7: cancelling can trigger an automatic partial refund or credit
    // note, depending on the plan's refund policy — worth a real confirm,
    // not a silent click.
    if (!window.confirm(`Cancel this subscription? Any refund due will be recorded as a credit note.`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.post<Detail>(`/billing/subscriptions/${id}/cancel`);
      setDetail(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel this subscription.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!detail) return <TableSkeleton rows={4} cols={5} />;

  const active = detail.status === "active";

  return (
    <>
      <PageHeader
        title={`${detail.quote_number} · ${detail.customer_name}`}
        subtitle="Opened by clicking a row on the Subscriptions list."
        actions={
          <>
            <StatusBadge status={detail.status} />
            <button className="btn" onClick={() => navigate(`/quotations/${detail.quotation_id}`)}>
              Open quotation
            </button>
            {detail.can_act && active && !modifying && (
              <>
                <button className="btn" disabled={busy} onClick={() => setModifying(true)}>
                  Modify Subscription
                </button>
                <button className="btn btn--danger" disabled={busy} onClick={() => void cancel()}>
                  Cancel Subscription
                </button>
              </>
            )}
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
            <div className="kpi__label">Plan</div>
            <div className="kpi__value">{detail.plan_name}</div>
            <div className="kpi__caption">{detail.product_name}</div>
          </div>
          <div className="card">
            <div className="kpi__label">Quantity × unit amount</div>
            <div className="kpi__value">
              {Number(detail.quantity)} × {money(detail.unit_amount)}
            </div>
          </div>
          <div className="card">
            <div className="kpi__label">Current cycle</div>
            <div className="kpi__value" style={{ fontSize: "1rem" }}>
              {dateTime(detail.current_cycle_start)} → {dateTime(detail.current_cycle_end)}
            </div>
          </div>
        </div>

        {modifying && (
          <div className="card">
            <h2 className="card__title">Modify subscription</h2>
            <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-end" }}>
              <div>
                <label className="sub-cell" style={{ display: "block", marginBottom: 4 }}>
                  Quantity
                </label>
                <input
                  className="input input--num"
                  type="number"
                  min="1"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                />
              </div>
              <div>
                <label className="sub-cell" style={{ display: "block", marginBottom: 4 }}>
                  Plan
                </label>
                <select
                  className="select"
                  value={planId}
                  onChange={(e) => setPlanId(Number(e.target.value))}
                >
                  {plans.map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name}
                    </option>
                  ))}
                </select>
              </div>
              <button className="btn btn--primary" disabled={busy} onClick={() => void saveModify()}>
                Save change
              </button>
              <button className="btn" onClick={() => setModifying(false)}>
                Cancel
              </button>
            </div>
            <div style={{ marginTop: "var(--space-3)" }}>
              <NoteBar>
                A quantity or plan change is priced with the daily-proration formula and recorded
                below immediately — the mid-cycle adjustment shows as its own recurring row.
              </NoteBar>
            </div>
          </div>
        )}

        <div className="card">
          <h2 className="card__title">One-time lines</h2>
          {oneTimeRows.length === 0 ? (
            <p className="muted">No one-time lines on this order.</p>
          ) : (
            <ScheduleTable rows={oneTimeRows} onRowClick={(rowId) => navigate(`/invoices/${rowId}`)} />
          )}
        </div>

        <div className="card">
          <h2 className="card__title">Recurring lines</h2>
          <ScheduleTable
            rows={detail.billing_schedules}
            onRowClick={(rowId) => navigate(`/invoices/${rowId}`)}
          />
        </div>

        <div className="card">
          <h2 className="card__title">Proration history</h2>
          {detail.proration_history.length === 0 ? (
            <p className="muted">No mid-cycle changes recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th className="num">Old qty</th>
                    <th className="num">New qty</th>
                    <th className="num">Credit</th>
                    <th className="num">Charge</th>
                    <th className="num">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.proration_history.map((record) => (
                    <tr key={record.id}>
                      <td>{dateTime(record.change_date)}</td>
                      <td className="num mono-num">{Number(record.old_quantity)}</td>
                      <td className="num mono-num">{Number(record.new_quantity)}</td>
                      <td className="num mono-num">{money(record.credit_amount)}</td>
                      <td className="num mono-num">{money(record.charge_amount)}</td>
                      <td className="num mono-num">
                        <strong>{money(record.proration_amount)}</strong>
                        {Number(record.proration_amount) < 0 && (
                          <div className="sub-cell">credit note</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {!detail.can_act && active && (
          <NoteBar>
            You can review this subscription, but only Finance/Operations can modify or cancel it.
          </NoteBar>
        )}
      </div>
    </>
  );
}

function ScheduleTable({
  rows,
  onRowClick,
}: {
  rows: BillingScheduleRow[];
  onRowClick: (id: number) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Due date</th>
            <th className="num">Amount</th>
            <th>Status</th>
            <th>Invoice</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="clickable" onClick={() => onRowClick(row.id)}>
              <td>{dateTime(row.due_date)}</td>
              <td className="num mono-num">
                {money(row.amount)}
                {row.is_credit_note && <div className="sub-cell">credit note</div>}
              </td>
              <td>
                <StatusBadge status={row.status} />
              </td>
              <td className="sub-cell">{row.invoice_number ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
