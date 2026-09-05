/** Screen 14 — Deal Health and Anomaly Dashboard. FRONTEND.md Section 5, PRD B9. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { DealHealthAlert, DealHealthDashboard as Dashboard } from "../lib/api";
import { dateTime } from "../lib/format";
import { EmptyState, ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

function issueLabel(alert: DealHealthAlert): string {
  const parts: string[] = [];
  if (alert.is_stalled) parts.push(`Idle ${alert.days_inactive} days`);
  if (alert.has_discount_anomaly) {
    parts.push(`Discount ${Number(alert.discount_vs_rep_average) > 0 ? "+" : ""}${alert.discount_vs_rep_average}pt vs rep avg`);
  }
  if (alert.has_delivery_slippage) parts.push(`Delivery ${alert.days_slipped} days late`);
  return parts.join(" · ");
}

export default function DealHealthDashboard() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDashboard(await api.get<Dashboard>("/deal-health"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load deal health data.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(quotationId: number, action: "nudge" | "escalate") {
    setBusyId(quotationId);
    setError(null);
    try {
      await api.post(`/deal-health/${quotationId}/${action}`);
      setNotice(action === "nudge" ? "Nudge sent." : "Escalated to Sales Manager.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete that action.");
    } finally {
      setBusyId(null);
    }
  }

  if (error && !dashboard) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!dashboard) return <TableSkeleton rows={4} cols={4} />;

  return (
    <>
      <PageHeader
        title="Deal Health"
        subtitle="Real-time flags for stalled deals and unusual discount patterns."
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

      <div className="grid-3" style={{ marginBottom: "var(--space-4)" }}>
        <div className="card">
          <div className="kpi__label">Stalled Deals</div>
          <div className="kpi__value">{dashboard.stalled_count}</div>
          <div className="kpi__caption">7+ days idle</div>
        </div>
        <div className="card">
          <div className="kpi__label">Discount Anomalies</div>
          <div className="kpi__value">{dashboard.anomaly_count}</div>
          <div className="kpi__caption">above rep average</div>
        </div>
        <div className="card">
          <div className="kpi__label">Delivery Slippage</div>
          <div className="kpi__value">{dashboard.slippage_count}</div>
          <div className="kpi__caption">promises at risk</div>
        </div>
      </div>

      {dashboard.alerts.length === 0 ? (
        <EmptyState
          title="Nothing flagged right now"
          hint="Deals appear here once they've been idle for a week, show an unusual discount, or slip a delivery promise."
        />
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Deal</th>
                  <th>Issue</th>
                  <th>Flagged</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.alerts.map((alert) => (
                  <tr key={alert.quotation_id}>
                    <td
                      className="primary-cell clickable"
                      onClick={() => navigate(`/quotations/${alert.quotation_id}`)}
                    >
                      {alert.quote_number}
                      <div className="sub-cell">
                        {alert.customer_name} · {alert.owner_name}
                      </div>
                    </td>
                    <td>{issueLabel(alert)}</td>
                    <td className="sub-cell">{dateTime(alert.snapshot_at)}</td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <button
                          className="btn btn--sm"
                          disabled={busyId === alert.quotation_id}
                          onClick={() => void act(alert.quotation_id, "nudge")}
                        >
                          Nudge Rep
                        </button>
                        <button
                          className="btn btn--sm"
                          disabled={busyId === alert.quotation_id}
                          onClick={() => void act(alert.quotation_id, "escalate")}
                        >
                          Escalate
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
