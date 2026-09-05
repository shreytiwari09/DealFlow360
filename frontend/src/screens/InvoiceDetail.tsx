/**
 * Screen 13 — Invoice Detail. FRONTEND.md Section 5, PRD B7 / Section 9.
 *
 * The status stepper mirrors `billing_schedules.status`'s own lifecycle:
 * Scheduled → Invoiced → Paid, guarded by the same `state_machine.py` table
 * as every other status in this app — "Issue Invoice" and "Record Payment"
 * are only offered when the transition is actually legal.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { InvoiceDetail as Detail } from "../lib/api";
import { dateTime, money } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, StatusBadge, Stepper, TableSkeleton } from "../components/ui";

const PAYMENT_METHODS = [
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "card", label: "Card" },
  { value: "cash", label: "Cash" },
  { value: "cheque", label: "Cheque" },
  { value: "other", label: "Other" },
];

export default function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("bank_transfer");
  const [payReference, setPayReference] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await api.get<Detail>(`/billing/invoices/${id}`);
      setDetail(d);
      setPayAmount(d.amount.startsWith("-") ? d.amount.slice(1) : d.amount);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this invoice.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function issue() {
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.post<Detail>(`/billing/invoices/${id}/issue`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not issue this invoice.");
    } finally {
      setBusy(false);
    }
  }

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.post<Detail>(`/billing/invoices/${id}/payments`, {
        amount: Number(payAmount),
        method: payMethod,
        reference: payReference || undefined,
      });
      setDetail(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record this payment.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!detail) return <TableSkeleton rows={4} cols={4} />;

  const stepState = (step: "scheduled" | "invoiced" | "paid") => {
    const order = ["scheduled", "invoiced", "paid"];
    if (detail.status === "cancelled") return "rejected" as const;
    const current = order.indexOf(detail.status);
    const mine = order.indexOf(step);
    if (mine < current) return "done" as const;
    if (mine === current) return "current" as const;
    return "upcoming" as const;
  };

  return (
    <>
      <PageHeader
        title={`${detail.invoice_number ?? detail.quote_number} · ${detail.customer_name}`}
        subtitle="Opened by clicking a row on the Invoices List."
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
        <div className="card">
          <Stepper
            steps={[
              { label: "Order Confirmed", state: "done" },
              { label: "Scheduled", state: stepState("scheduled") },
              { label: "Invoiced", state: stepState("invoiced") },
              { label: "Paid", state: stepState("paid") },
            ]}
          />
        </div>

        <div className="grid-3">
          <div className="card">
            <div className="kpi__label">Amount</div>
            <div className="kpi__value">{money(detail.amount)}</div>
            {detail.is_credit_note && <div className="kpi__caption">Credit note</div>}
          </div>
          <div className="card">
            <div className="kpi__label">Type</div>
            <div className="kpi__value" style={{ fontSize: "1.1rem" }}>
              {detail.schedule_type === "one_time" ? "One-time" : "Recurring"}
            </div>
            {detail.cycle_start && detail.cycle_end && (
              <div className="kpi__caption">
                {dateTime(detail.cycle_start)} → {dateTime(detail.cycle_end)}
              </div>
            )}
          </div>
          <div className="card">
            <div className="kpi__label">Due date</div>
            <div className="kpi__value" style={{ fontSize: "1.1rem" }}>
              {dateTime(detail.due_date)}
            </div>
          </div>
        </div>

        {detail.can_act && detail.status === "scheduled" && (
          <div className="card">
            <div className="row row--between">
              <p className="muted" style={{ margin: 0 }}>
                Issue this invoice to assign it a number before recording a payment.
              </p>
              <button className="btn btn--primary" disabled={busy} onClick={() => void issue()}>
                Issue Invoice
              </button>
            </div>
          </div>
        )}

        {detail.can_act && detail.status === "invoiced" && (
          <div className="card">
            <h2 className="card__title">Record a payment</h2>
            <div className="row" style={{ gap: "var(--space-4)", alignItems: "flex-end", flexWrap: "wrap" }}>
              <div className="field">
                <label className="field__label">
                  Amount
                </label>
                <input
                  className="input input--num"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={payAmount}
                  onChange={(e) => setPayAmount(e.target.value)}
                />
              </div>
              <div className="field">
                <label className="field__label">
                  Method
                </label>
                <select className="select" value={payMethod} onChange={(e) => setPayMethod(e.target.value)}>
                  {PAYMENT_METHODS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field__label">
                  Reference (optional)
                </label>
                <input
                  className="input"
                  value={payReference}
                  onChange={(e) => setPayReference(e.target.value)}
                  placeholder="Transaction ID"
                />
              </div>
              <button className="btn btn--primary" disabled={busy} onClick={() => void pay()}>
                Record Payment
              </button>
            </div>
          </div>
        )}

        <div className="card">
          <h2 className="card__title">Payment history</h2>
          {detail.payments.length === 0 ? (
            <p className="muted">No payments recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Paid at</th>
                    <th className="num">Amount</th>
                    <th>Method</th>
                    <th>Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{dateTime(p.paid_at)}</td>
                      <td className="num mono-num">{money(p.amount)}</td>
                      <td>{p.method}</td>
                      <td className="sub-cell">{p.reference ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {!detail.can_act && detail.status !== "paid" && detail.status !== "cancelled" && (
          <NoteBar>
            You can review this invoice, but only Finance/Operations can issue it or record a
            payment.
          </NoteBar>
        )}
      </div>
    </>
  );
}
