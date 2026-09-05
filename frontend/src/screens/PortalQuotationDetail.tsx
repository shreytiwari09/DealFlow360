/**
 * Screen 11 — Customer Portal Negotiation Screen. FRONTEND.md Section 5, PRD B8.
 *
 * Explicit constraint from FRONTEND.md: this screen must never expose any
 * internal-only control, data field, or navigation item — no discount
 * limits, no other customers' data, no internal audit trail, no role or
 * permission info. That is enforced by the backend's separate portal schemas
 * (there is no field here to leak in the first place), not by this component
 * choosing not to render one.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { PortalConfirmResult, PortalQuotationDetail as Detail } from "../lib/api";
import { dateTime, money, percent } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

export default function PortalQuotationDetail() {
  const { id } = useParams<{ id: string }>();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [comment, setComment] = useState("");
  const [counterDiscount, setCounterDiscount] = useState("");
  const [requestedDeliveryDate, setRequestedDeliveryDate] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setDetail(await api.get<Detail>(`/portal/quotations/${id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this quotation.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * `Requested Delivery Date` has no column of its own — Locked Business
   * Rules #8c — so it rides along inside the free-text message rather than
   * being a separate structured field the backend would otherwise ignore.
   */
  function composeMessage(): string {
    if (!requestedDeliveryDate) return comment;
    return `${comment}\n\nRequested delivery: ${requestedDeliveryDate}`;
  }

  async function submitRequest() {
    if (!comment.trim()) {
      setError("Please add a comment before submitting.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.post<Detail>(`/portal/quotations/${id}/negotiate`, {
        comment: composeMessage(),
        counter_discount_percent: counterDiscount ? Number(counterDiscount) : undefined,
      });
      setDetail(updated);
      setComment("");
      setCounterDiscount("");
      setRequestedDeliveryDate("");
      setNotice("Your request has been sent to the sales team.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit your request.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmQuotation() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.post<PortalConfirmResult>(`/portal/quotations/${id}/confirm`);
      setDetail(result.quotation);
      setNotice(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm this quotation.");
      if (err instanceof ApiError && err.status === 409) void load();
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!detail) return <TableSkeleton rows={4} cols={4} />;

  return (
    <>
      <PageHeader
        title={detail.quote_number}
        subtitle="Review and negotiate your quote directly — no email needed."
        actions={<StatusBadge status={detail.status} />}
      />

      {notice && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar>{notice}</NoteBar>
        </div>
      )}
      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="stack">
        <div className="card">
          <div className="grid-3">
            <div>
              <div className="kpi__label">Total</div>
              <div className="kpi__value">{money(detail.total_amount, detail.currency)}</div>
            </div>
            <div>
              <div className="kpi__label">Discount</div>
              <div className="kpi__value">{money(detail.discount_amount, detail.currency)}</div>
            </div>
            <div>
              <div className="kpi__label">Valid until</div>
              <div className="kpi__value" style={{ fontSize: "1.1rem" }}>
                {detail.valid_until ? dateTime(detail.valid_until) : "—"}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">Lines</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="num">Qty</th>
                  <th className="num">Price</th>
                  <th className="num">Discount</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {detail.lines.map((line) => (
                  <tr key={line.line_number}>
                    <td className="primary-cell">{line.product_name}</td>
                    <td className="num mono-num">{Number(line.quantity)}</td>
                    <td className="num mono-num">{money(line.unit_list_price, detail.currency)}</td>
                    <td className="num mono-num">{percent(line.discount_percent)}</td>
                    <td className="num mono-num">{money(line.line_total, detail.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">Comments &amp; requests</h2>
          {detail.comments.length === 0 ? (
            <p className="muted">No messages yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>From</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.comments.map((c, i) => (
                    <tr key={i}>
                      <td className="sub-cell">{dateTime(c.created_at)}</td>
                      <td className="sub-cell">{c.author_name ?? "You"}</td>
                      <td style={{ whiteSpace: "pre-wrap" }}>{c.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {detail.can_negotiate && (
          <div className="card">
            <h2 className="card__title">Request a change</h2>
            <div className="stack" style={{ gap: "var(--space-3)" }}>
              <div className="field">
                <label className="field__label">Comment</label>
                <textarea
                  className="textarea"
                  rows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="e.g. Can we get 10% instead of 5% on the Setup Service?"
                />
              </div>
              <div className="row" style={{ gap: "var(--space-4)", flexWrap: "wrap" }}>
                <div className="field">
                  <label className="field__label">Counter Discount %</label>
                  <input
                    className="input input--num"
                    type="number"
                    min="0"
                    max="100"
                    step="0.5"
                    value={counterDiscount}
                    onChange={(e) => setCounterDiscount(e.target.value)}
                    placeholder="Optional"
                  />
                </div>
                <div className="field">
                  <label className="field__label">Requested Delivery Date</label>
                  <input
                    className="input"
                    type="date"
                    value={requestedDeliveryDate}
                    onChange={(e) => setRequestedDeliveryDate(e.target.value)}
                  />
                </div>
              </div>
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => void submitRequest()}>
                  Submit Request
                </button>
                <button
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => void confirmQuotation()}
                >
                  Confirm Quotation
                </button>
              </div>
              <NoteBar>
                If final terms exceed approval thresholds, the quote automatically re-enters
                approval with our sales team.
              </NoteBar>
            </div>
          </div>
        )}

        {!detail.can_negotiate && (
          <NoteBar>
            {detail.status === "confirmed"
              ? "This order is confirmed. Thank you!"
              : "This quotation is no longer open for negotiation."}
          </NoteBar>
        )}
      </div>
    </>
  );
}
