/**
 * Screen 4 — Quotation Detail / Builder. FRONTEND.md Section 5.
 *
 * This is the screen the whole product is judged on: the live blended risk
 * score, the per-line ceiling, and the OVER LIMIT flag that appears as soon
 * as a discount is entered rather than only at submit time.
 *
 * The score is always computed by the backend and displayed here. It is never
 * calculated client-side — FRONTEND.md Screen 18's explicit dependency.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { Product, Quotation, RiskPreview } from "../lib/api";
import { humanise, money, percent, points } from "../lib/format";
import {
  ErrorState,
  NoteBar,
  OverLimitBadge,
  PageHeader,
  RiskBadge,
  StatusBadge,
  TableSkeleton,
} from "../components/ui";

interface DraftLine {
  product_id: number;
  quantity: string;
  discount_percent: string;
  added_from_upsell: boolean;
}

export default function QuotationDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [risk, setRisk] = useState<RiskPreview | null>(null);
  const [draft, setDraft] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  /*
   * The draft is mirrored into a ref, and every save reads the ref rather
   * than the `draft` state variable.
   *
   * This is not belt-and-braces. An onBlur handler closes over the values
   * from the render it was created in, so typing a discount and immediately
   * blurring can fire a handler whose `draft` and `dirty` are one render
   * behind - and the edit is silently dropped. A ref always holds the latest
   * value regardless of render timing.
   */
  const draftRef = useRef<DraftLine[]>([]);
  const debounceRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [q, p] = await Promise.all([
        api.get<Quotation>(`/quotations/${id}`),
        api.get<Product[]>("/products"),
      ]);
      setQuotation(q);
      setProducts(p);
      const lines = q.lines.map((line) => ({
        product_id: line.product_id,
        quantity: line.quantity,
        discount_percent: line.discount_percent,
        added_from_upsell: line.added_from_upsell,
      }));
      setDraft(lines);
      draftRef.current = lines;
      setRisk(await api.get<RiskPreview>(`/quotations/${id}/risk`));
      setDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this quotation.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Persist the line set, then re-read totals and risk from the response.
   * The server is the only thing that computes the score, so "live" here
   * means "saved and recomputed", not "guessed locally".
   */
  const save = useCallback(
    async (lines: DraftLine[]) => {
      if (!quotation) return;
      setSaving(true);
      setError(null);
      try {
        const updated = await api.put<Quotation>(`/quotations/${quotation.id}/lines`, {
          lines: lines.map((line) => ({
            product_id: line.product_id,
            quantity: Number(line.quantity) || 0,
            discount_percent: Number(line.discount_percent) || 0,
            added_from_upsell: line.added_from_upsell,
          })),
        });
        setQuotation(updated);
        setRisk(await api.get<RiskPreview>(`/quotations/${quotation.id}/risk`));
        setDirty(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not save the lines.");
      } finally {
        setSaving(false);
      }
    },
    [quotation],
  );

  /** Save whatever the ref currently holds. Immune to render timing. */
  const flush = useCallback(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    void save(draftRef.current);
  }, [save]);

  // Cancel a pending debounce if the screen goes away mid-edit.
  useEffect(
    () => () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    },
    [],
  );

  function addProduct(productId: number, fromUpsell = false) {
    const next = [
      ...draftRef.current,
      { product_id: productId, quantity: "1", discount_percent: "0", added_from_upsell: fromUpsell },
    ];
    setDraft(next);
    draftRef.current = next;
    void save(next);
  }

  /**
   * Edit a line and schedule a save.
   *
   * The debounce is what makes the risk score genuinely live: the rep types a
   * discount and the score, margin and OVER LIMIT badge update a moment later
   * without needing to click anything. Blur flushes immediately.
   */
  function updateLine(index: number, patch: Partial<DraftLine>) {
    const next = draftRef.current.map((line, i) =>
      i === index ? { ...line, ...patch } : line,
    );
    draftRef.current = next;
    setDraft(next);
    setDirty(true);

    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void save(draftRef.current);
    }, 600);
  }

  function removeLine(index: number) {
    const next = draftRef.current.filter((_, i) => i !== index);
    setDraft(next);
    draftRef.current = next;
    void save(next);
  }

  async function submitForApproval() {
    if (!quotation) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.post<Quotation>(`/quotations/${quotation.id}/submit`);
      setQuotation(updated);
      navigate("/approvals");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit for approval.");
      if (err instanceof ApiError && err.status === 409) void load();
    } finally {
      setSaving(false);
    }
  }

  /**
   * Records that the customer has confirmed, unlocking fulfillment.
   *
   * A temporary internal stand-in for the customer's own "Confirm Quotation"
   * action on the portal negotiation screen (PRD B8), which is not built yet
   * — see the backend endpoint's docstring. Shown only once a quotation has
   * cleared approval (or never needed it), matching the states the state
   * machine allows a direct jump to `confirmed` from.
   */
  async function confirmQuotation() {
    if (!quotation) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.post<Quotation>(`/quotations/${quotation.id}/confirm`);
      setQuotation(updated);
      navigate(`/fulfillment/${quotation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm this quotation.");
    } finally {
      setSaving(false);
    }
  }

  const canConfirm = ["approved", "sent", "under_negotiation"].includes(quotation?.status ?? "");

  /**
   * Upsell suggestions (PRD B5). The seeded rules live server-side; until the
   * rules endpoint exists this surfaces promoted products not already on the
   * quote, which is the same shape of suggestion the panel will show.
   */
  const suggestions = useMemo(() => {
    const onQuote = new Set(draft.map((line) => line.product_id));
    return products.filter((p) => p.is_promoted && !onQuote.has(p.id)).slice(0, 3);
  }, [products, draft]);

  if (loading) return <TableSkeleton rows={5} cols={6} />;
  if (error && !quotation) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!quotation) return null;

  // `can_edit` from the backend is permission + ownership only, not status —
  // it stays true even once a quote is approved/sent/confirmed. The backend
  // separately rejects a line edit with 409 unless the quotation is actually
  // draft or rejected, so the UI must apply that same status gate itself, or
  // it shows live-editable discount fields that would fail the moment you
  // click away from them.
  const editable = quotation.can_edit && ["draft", "rejected"].includes(quotation.status);

  return (
    <>
      <PageHeader
        title={`${quotation.quote_number} · ${quotation.customer_name}`}
        subtitle="Add products, apply discounts, review specifics."
        actions={
          <>
            <StatusBadge status={quotation.status} />
            {editable && (
              <>
                <button
                  className="btn"
                  disabled={saving || !dirty}
                  onClick={flush}
                >
                  {saving ? "Saving…" : "Save Draft"}
                </button>
                <button
                  className="btn btn--primary"
                  disabled={saving || draft.length === 0}
                  onClick={() => void submitForApproval()}
                >
                  Submit for Approval
                </button>
              </>
            )}
            {canConfirm && (
              <button className="btn btn--primary" disabled={saving} onClick={() => void confirmQuotation()}>
                Confirm Quotation
              </button>
            )}
          </>
        }
      />

      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="split">
        <div className="stack">
          {/* --- Live indicators ------------------------------------------- */}
          <div className="grid-3">
            <div className="card">
              <div className="kpi__label">Order total</div>
              <div className="kpi__value">{money(quotation.total_amount, quotation.currency)}</div>
              <div className="kpi__caption">
                {money(quotation.discount_amount, quotation.currency)} discounted
              </div>
            </div>
            <div className="card">
              <div className="kpi__label">Live margin</div>
              <div className="kpi__value">{percent(quotation.margin_percent)}</div>
              <div className="kpi__caption">
                {money(quotation.margin_amount, quotation.currency)}
              </div>
            </div>
            <div className="card">
              <div className="kpi__label">Blended risk score</div>
              <div className="kpi__value">
                {Number(quotation.blended_risk_score).toFixed(2)}{" "}
                {risk && <RiskBadge band={risk.risk_band} />}
              </div>
              <div className="kpi__caption">
                {risk?.requires_approval
                  ? `Routes to ${risk.required_steps.map(humanise).join(" → ")}`
                  : "Within policy — no approval needed"}
              </div>
            </div>
          </div>

          {risk?.finance_gate_tripped && (
            <NoteBar tone="warning">
              One line is more than 15 points over its own limit, so this quotation needs
              Finance approval regardless of the blended score.
            </NoteBar>
          )}

          {/* --- Line items ------------------------------------------------ */}
          <div>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="num">Qty</th>
                    <th className="num">Price</th>
                    <th className="num">Discount</th>
                    <th className="num">Limit</th>
                    <th>Status</th>
                    {editable && <th />}
                  </tr>
                </thead>
                <tbody>
                  {quotation.lines.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted" style={{ textAlign: "center" }}>
                        No lines yet — add a product to begin.
                      </td>
                    </tr>
                  )}
                  {quotation.lines.map((line, index) => (
                    <tr key={line.id}>
                      <td>
                        <div className="primary-cell">{line.product_name}</div>
                        <div className="sub-cell">
                          {line.product_sku}
                          {line.added_from_upsell && " · added from upsell"}
                        </div>
                      </td>
                      <td className="num">
                        {editable ? (
                          <input
                            className="input input--num"
                            type="number"
                            min="1"
                            value={draft[index]?.quantity ?? line.quantity}
                            onChange={(e) => updateLine(index, { quantity: e.target.value })}
                            onBlur={flush}
                          />
                        ) : (
                          Number(line.quantity)
                        )}
                      </td>
                      <td className="num mono-num">{money(line.unit_list_price, quotation.currency)}</td>
                      <td className="num">
                        {editable ? (
                          /* TBD #4: the wireframe shows only the resulting
                             columns, so this is the minimum control that makes
                             the row functional — an inline percentage field. */
                          <input
                            className="input input--num"
                            type="number"
                            min="0"
                            max="100"
                            step="0.5"
                            value={draft[index]?.discount_percent ?? line.discount_percent}
                            onChange={(e) =>
                              updateLine(index, { discount_percent: e.target.value })
                            }
                            onBlur={flush}
                          />
                        ) : (
                          percent(line.discount_percent)
                        )}
                      </td>
                      <td className="num mono-num muted">
                        {percent(line.allowed_discount_percent)}
                      </td>
                      <td>
                        <OverLimitBadge over={line.is_over_limit} />
                        {line.is_over_limit && (
                          <div className="sub-cell">{points(line.line_excess_points)} over</div>
                        )}
                      </td>
                      {editable && (
                        <td>
                          <button
                            className="btn btn--sm"
                            onClick={() => removeLine(index)}
                            aria-label={`Remove ${line.product_name}`}
                          >
                            Remove
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: "var(--space-3)" }}>
              <NoteBar>
                Discount is checked against each line&apos;s own limit, not just an overall
                limit — one line over triggers approval, even if others are fine.
              </NoteBar>
            </div>
          </div>
        </div>

        {/* --- Right rail: add products + upsell panel --------------------- */}
        <div className="stack">
          {editable && (
            <div className="card">
              <h2 className="card__title">Add a product</h2>
              <select
                className="select"
                value=""
                onChange={(e) => e.target.value && addProduct(Number(e.target.value))}
              >
                <option value="">Choose a product…</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id}>
                    {product.name} · {money(product.list_price, quotation.currency)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {editable && suggestions.length > 0 && (
            <div className="card">
              <h2 className="card__title">Upsell &amp; cross-sell</h2>
              {suggestions.map((product) => (
                <div key={product.id} className="row row--between" style={{ marginBottom: 8 }}>
                  <div>
                    <div className="primary-cell">{product.name}</div>
                    <div className="sub-cell">
                      <span className="badge badge--accent">Promoted</span>
                    </div>
                  </div>
                  <button
                    className="btn btn--sm"
                    onClick={() => addProduct(product.id, true)}
                  >
                    + Add
                  </button>
                </div>
              ))}
              <NoteBar>Adding a suggestion updates the margin indicator immediately.</NoteBar>
            </div>
          )}

          {risk && risk.lines.some((line) => Number(line.excess_points) > 0) && (
            <div className="card">
              <h2 className="card__title">Why this will be flagged</h2>
              <table className="data">
                <tbody>
                  {risk.lines
                    .filter((line) => Number(line.excess_points) > 0)
                    .map((line) => (
                      <tr key={line.line_number}>
                        <td>
                          <div className="primary-cell">{line.product_name}</div>
                          <div className="sub-cell">
                            {percent(line.discount_percent)} given ·{" "}
                            {percent(line.allowed_discount_percent)} allowed
                          </div>
                        </td>
                        <td className="num">
                          <span className="badge badge--error">
                            {points(line.excess_points)} over
                          </span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
