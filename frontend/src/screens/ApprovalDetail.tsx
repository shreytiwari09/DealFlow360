/**
 * Screen 6 — Approval Detail. FRONTEND.md Section 5.
 *
 * The "Why This Quote Was Flagged" table is the direct UI expression of the
 * PRD Section 10 worked example, and the wording is kept aligned with it so
 * the demo and the viva say the same thing.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { ApprovalDetail as Detail } from "../lib/api";
import { dateTime, money, percent, points } from "../lib/format";
import {
  ErrorState,
  NoteBar,
  PageHeader,
  RiskBadge,
  StatusBadge,
  Stepper,
  TableSkeleton,
} from "../components/ui";

type StepState = "done" | "current" | "upcoming" | "skipped" | "rejected";

export default function ApprovalDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDetail(await api.get<Detail>(`/approvals/${id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this approval.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(decision: "approve" | "reject" | "return") {
    if (!detail) return;
    if (!reason.trim()) {
      setError("A reason is required — every decision is recorded in the audit trail.");
      return;
    }
    if (decision === "reject" && !window.confirm("Reject this quotation? This cannot be undone.")) {
      return;
    }
    // Disabled while in flight, so a double-click cannot double-submit —
    // FRONTEND.md Section 7 and PLAN.md Phase 9.
    setBusy(true);
    setError(null);
    try {
      setDetail(await api.post<Detail>(`/approvals/${detail.id}/decide`, { decision, reason }));
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the decision.");
      void load();
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!detail) return <TableSkeleton rows={4} cols={4} />;

  const steps: { label: string; state: StepState; hint?: string }[] = [
    { label: "Submitted", state: "done" },
    ...detail.steps.map((step) => ({
      label: step.required_role,
      state: (step.status === "approved"
        ? "done"
        : step.status === "rejected" || step.status === "returned_for_revision"
          ? "rejected"
          : detail.current_stage === step.required_role
            ? "current"
            : "upcoming") as StepState,
      hint: step.forced_by_line_gate ? "required by single-line gate" : undefined,
    })),
    {
      label: "Confirmed",
      state: detail.status === "approved" ? "done" : "upcoming",
    },
  ];

  const flagged = detail.line_breakdown.filter((line) => Number(line.excess_points) > 0);

  return (
    <>
      <PageHeader
        title={`${detail.quote_number} · ${detail.customer_name}`}
        subtitle="Approval review and audit trail."
        actions={
          <>
            <RiskBadge band={detail.risk_band} />
            <span className="badge badge--neutral">Tier: {detail.customer_tier}</span>
            <StatusBadge status={detail.status} />
            <button className="btn" onClick={() => navigate(`/quotations/${detail.quotation_id}`)}>
              Open quotation
            </button>
          </>
        }
      />

      <div className="stack">
        <div className="card">
          <h2 className="card__title">Approval steps</h2>
          <Stepper steps={steps} />
          {detail.triggered_by_line_gate && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <NoteBar tone="warning">
                Finance approval was added because one line is{" "}
                {points(detail.max_line_excess)} over its own limit — more than the
                15-point single-line threshold — regardless of the blended score.
              </NoteBar>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="card__title">Why this quote was flagged</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Line</th>
                  <th className="num">Discount given</th>
                  <th className="num">Limit allowed</th>
                  <th className="num">Over by</th>
                </tr>
              </thead>
              <tbody>
                {detail.line_breakdown.map((line) => {
                  const over = Number(line.excess_points) > 0;
                  return (
                    <tr key={line.line_number}>
                      <td className="primary-cell">{line.product_name}</td>
                      <td className="num mono-num">{percent(line.discount_percent)}</td>
                      <td className="num mono-num">{percent(line.allowed_discount_percent)}</td>
                      <td className="num">
                        {over ? (
                          <span className="badge badge--error">
                            {points(line.excess_points)} OVER
                          </span>
                        ) : (
                          <span className="badge badge--success">0 pt — OK</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: "var(--space-3)" }}>
            <NoteBar>
              {flagged.length > 0 ? (
                <>
                  Even though the tier allows a higher headline discount, a line broke its own
                  stricter limit — this is what triggers blended scoring. Blended risk score{" "}
                  <strong>{Number(detail.blended_risk_score).toFixed(2)}</strong>, order value{" "}
                  {money(detail.total_amount, detail.currency)}.
                </>
              ) : (
                <>No line exceeded its own limit.</>
              )}
            </NoteBar>
          </div>
        </div>

        {detail.can_act && detail.status === "pending" && (
          <div className="card">
            <h2 className="card__title">Your decision — {detail.current_stage}</h2>
            <label className="field">
              <span className="field__label">
                Reason (required — recorded against your name in the audit trail)
              </span>
              <textarea
                className="textarea"
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            {error && <div className="field__error">{error}</div>}
            <div className="row" style={{ marginTop: "var(--space-3)" }}>
              <button
                className="btn btn--success"
                disabled={busy}
                onClick={() => void decide("approve")}
              >
                {busy ? "Working…" : "Approve"}
              </button>
              <button className="btn" disabled={busy} onClick={() => void decide("return")}>
                Return for Revision
              </button>
              <button
                className="btn btn--danger"
                disabled={busy}
                onClick={() => void decide("reject")}
              >
                Reject
              </button>
            </div>
          </div>
        )}

        {!detail.can_act && detail.status === "pending" && (
          <NoteBar>
            This is waiting on {detail.current_stage}. You can review it, but you cannot act
            on the current step.
          </NoteBar>
        )}

        <div className="card">
          <h2 className="card__title">Audit trail</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Action</th>
                  <th>Date</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {detail.audit_trail.map((entry, index) => (
                  <tr key={index}>
                    <td className="primary-cell">{entry.user_name ?? "System"}</td>
                    <td className="sub-cell">{entry.action}</td>
                    <td className="sub-cell">{dateTime(entry.created_at)}</td>
                    <td className="sub-cell">{entry.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
