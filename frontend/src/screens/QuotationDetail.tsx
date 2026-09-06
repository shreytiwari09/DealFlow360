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
import type {
  AssignableUser,
  Product,
  Quotation,
  RiskPreview,
  SubscriptionPlan,
  UpsellSuggestion,
} from "../lib/api";
import { humanise, money, percent, points } from "../lib/format";
import { useAuth } from "../lib/auth";
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
  // Required for a subscription product, forbidden for a one-time product —
  // the backend enforces this against the product's real item_type; this is
  // just what lets the row show/collect the plan choice.
  subscription_plan_id: number | null;
}

export default function QuotationDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { can } = useAuth();

  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [assignableUsers, setAssignableUsers] = useState<AssignableUser[] | null>(null);
  const [showReassign, setShowReassign] = useState(false);
  const [selectedAssigneeId, setSelectedAssigneeId] = useState("");
  const [reassigning, setReassigning] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [risk, setRisk] = useState<RiskPreview | null>(null);
  const [draft, setDraft] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [orderDiscount, setOrderDiscount] = useState("");
  const [suggestions, setSuggestions] = useState<UpsellSuggestion[]>([]);
  // Session-local only (PRD B5's "Dismiss" has no persistence requirement,
  // and FRONTEND.md leaves the affordance's exact behaviour TBD) - a
  // dismissed suggestion can reappear next visit, but not this one.
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

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

  /**
   * Re-fetches ranked suggestions (PRD B5). Called whenever the lines or
   * discounts change, since both the "already on quote" exclusion and the
   * live margin-delta figure depend on the quotation's current state.
   * Failure here is non-fatal — the panel just stays empty — since it must
   * never block the rest of the builder from working.
   */
  const loadSuggestions = useCallback(async (quotationId: number) => {
    try {
      setSuggestions(await api.get<UpsellSuggestion[]>(`/quotations/${quotationId}/upsell`));
    } catch {
      setSuggestions([]);
    }
  }, []);

  async function openReassign() {
    setError(null);
    setShowReassign(true);
    if (!assignableUsers) {
      try {
        setAssignableUsers(await api.get<AssignableUser[]>("/quotations/assignable-users"));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load the rep list.");
        setShowReassign(false);
      }
    }
  }

  async function reassign() {
    if (!quotation || !selectedAssigneeId) return;
    setReassigning(true);
    setError(null);
    try {
      const updated = await api.patch<Quotation>(`/quotations/${quotation.id}/assign`, {
        new_owner_id: Number(selectedAssigneeId),
      });
      setQuotation(updated);
      setShowReassign(false);
      setSelectedAssigneeId("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reassign this quotation.");
    } finally {
      setReassigning(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [q, p, plansList] = await Promise.all([
        api.get<Quotation>(`/quotations/${id}`),
        api.get<Product[]>("/products"),
        api.get<SubscriptionPlan[]>("/subscription-plans"),
      ]);
      setQuotation(q);
      setProducts(p);
      setPlans(plansList);
      const lines = q.lines.map((line) => ({
        product_id: line.product_id,
        quantity: line.quantity,
        discount_percent: line.discount_percent,
        added_from_upsell: line.added_from_upsell,
        subscription_plan_id: line.subscription_plan_id,
      }));
      setDraft(lines);
      draftRef.current = lines;
      setRisk(await api.get<RiskPreview>(`/quotations/${id}/risk`));
      setDirty(false);
      void loadSuggestions(q.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this quotation.");
    } finally {
      setLoading(false);
    }
  }, [id, loadSuggestions]);

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
            subscription_plan_id: line.subscription_plan_id,
          })),
        });
        setQuotation(updated);
        setRisk(await api.get<RiskPreview>(`/quotations/${quotation.id}/risk`));
        setDirty(false);
        void loadSuggestions(updated.id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not save the lines.");
      } finally {
        setSaving(false);
      }
    },
    [quotation, loadSuggestions],
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
    const product = products.find((p) => p.id === productId);
    // A subscription line needs a plan the moment it's created — the CHECK
    // constraint would reject a save with none, so default to the first
    // active plan rather than saving a half-built line the rep then has to
    // notice and fix via the (not-yet-visible-as-an-error) Plan column.
    const defaultPlanId =
      product?.item_type === "subscription" ? (plans[0]?.id ?? null) : null;
    const next = [
      ...draftRef.current,
      {
        product_id: productId,
        quantity: "1",
        discount_percent: "0",
        added_from_upsell: fromUpsell,
        subscription_plan_id: defaultPlanId,
      },
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
  /**
   * Order-level discount (PRD B3, Locked Business Rules #4): distributes one
   * percentage onto EVERY line, overwriting whatever was there. That is
   * destructive to any manually-set per-line discount, so the caller (this
   * component) is responsible for warning first — the backend applies it
   * unconditionally the moment it is called.
   */
  async function applyOrderDiscount() {
    if (!quotation) return;
    const value = Number(orderDiscount);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      setError("Enter a discount between 0 and 100.");
      return;
    }
    if (
      !window.confirm(
        `Apply ${value}% to every line? This overwrites any discount already set per line.`,
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.post<Quotation>(`/quotations/${quotation.id}/order-discount`, {
        discount_percent: value,
      });
      setQuotation(updated);
      const lines = updated.lines.map((line) => ({
        product_id: line.product_id,
        quantity: line.quantity,
        discount_percent: line.discount_percent,
        added_from_upsell: line.added_from_upsell,
        subscription_plan_id: line.subscription_plan_id,
      }));
      setDraft(lines);
      draftRef.current = lines;
      setRisk(await api.get<RiskPreview>(`/quotations/${quotation.id}/risk`));
      setOrderDiscount("");
      void loadSuggestions(updated.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply the order-level discount.");
    } finally {
      setSaving(false);
    }
  }

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

  // PRD B5's ranked panel, minus whatever the rep dismissed this visit.
  const visibleSuggestions = useMemo(
    () => suggestions.filter((s) => !dismissed.has(s.product_id)),
    [suggestions, dismissed],
  );

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

      <div className="row" style={{ gap: "var(--space-2)", alignItems: "center", marginBottom: "var(--space-3)" }}>
        <span className="muted">
          Owned by <strong>{quotation.owner_name}</strong>
        </span>
        {can("deal.assign") && !showReassign && (
          <button type="button" className="btn btn--sm" onClick={() => void openReassign()}>
            Reassign
          </button>
        )}
      </div>

      {showReassign && (
        <div className="card" style={{ marginBottom: "var(--space-4)" }}>
          {!assignableUsers ? (
            <p className="muted">Loading…</p>
          ) : (
            <div className="row" style={{ gap: "var(--space-3)", alignItems: "flex-end" }}>
              <div className="field">
                <label className="field__label">Reassign to</label>
                <select
                  className="select"
                  value={selectedAssigneeId}
                  onChange={(e) => setSelectedAssigneeId(e.target.value)}
                >
                  <option value="">Choose…</option>
                  {assignableUsers
                    .filter((u) => u.id !== quotation.owner_id)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name} ({u.role_name})
                      </option>
                    ))}
                </select>
              </div>
              <button
                className="btn btn--primary"
                disabled={reassigning || !selectedAssigneeId}
                onClick={() => void reassign()}
              >
                {reassigning ? "Reassigning…" : "Confirm reassign"}
              </button>
              <button className="btn" onClick={() => setShowReassign(false)}>
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

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
                    <th>Plan</th>
                    <th>Status</th>
                    {editable && <th />}
                  </tr>
                </thead>
                <tbody>
                  {quotation.lines.length === 0 && (
                    <tr>
                      <td colSpan={8} className="muted" style={{ textAlign: "center" }}>
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
                        {line.line_type !== "subscription" ? (
                          <span className="muted">—</span>
                        ) : editable ? (
                          <select
                            className="select"
                            value={draft[index]?.subscription_plan_id ?? line.subscription_plan_id ?? ""}
                            onChange={(e) => {
                              updateLine(index, { subscription_plan_id: Number(e.target.value) });
                              flush();
                            }}
                          >
                            <option value="" disabled>
                              Choose a plan…
                            </option>
                            {plans.map((plan) => (
                              <option key={plan.id} value={plan.id}>
                                {plan.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                          line.subscription_plan_name ?? "—"
                        )}
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

          {editable && quotation.lines.length > 0 && (
            <div className="card">
              <h2 className="card__title">Order-level discount</h2>
              <div className="row" style={{ gap: "var(--space-2)" }}>
                <input
                  className="input input--num"
                  type="number"
                  min="0"
                  max="100"
                  step="0.5"
                  value={orderDiscount}
                  onChange={(e) => setOrderDiscount(e.target.value)}
                  placeholder="%"
                />
                <button
                  className="btn"
                  disabled={saving || !orderDiscount}
                  onClick={() => void applyOrderDiscount()}
                >
                  Apply to all lines
                </button>
              </div>
              <div style={{ marginTop: "var(--space-2)" }}>
                <NoteBar>
                  Overwrites every line&apos;s discount with this one percentage — it does not
                  stack with what is already there.
                </NoteBar>
              </div>
            </div>
          )}

          {editable && visibleSuggestions.length > 0 && (
            <div className="card">
              <h2 className="card__title">Upsell &amp; cross-sell</h2>
              {visibleSuggestions.map((s) => {
                const delta = Number(s.margin_delta_percent);
                return (
                  <div key={s.product_id} className="row row--between" style={{ marginBottom: 8 }}>
                    <div>
                      <div className="primary-cell">{s.product_name}</div>
                      <div className="sub-cell">
                        {s.is_promoted && (
                          <span className="badge badge--accent" style={{ marginRight: 6 }}>
                            Promoted
                          </span>
                        )}
                        <span className={delta >= 0 ? "badge badge--success" : "badge badge--warning"}>
                          {delta >= 0 ? "+" : ""}
                          {delta.toFixed(2)}% margin
                        </span>
                      </div>
                    </div>
                    <div className="row" style={{ gap: 4 }}>
                      <button
                        className="btn btn--sm"
                        onClick={() =>
                          setDismissed((current) => new Set(current).add(s.product_id))
                        }
                      >
                        Dismiss
                      </button>
                      <button className="btn btn--sm btn--primary" onClick={() => addProduct(s.product_id, true)}>
                        + Add
                      </button>
                    </div>
                  </div>
                );
              })}
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
