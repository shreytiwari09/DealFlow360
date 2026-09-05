/** Screen 2 — Sales Dashboard. FRONTEND.md Section 5. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Customer, DashboardSummary, Quotation } from "../lib/api";
import { dateTime, humanise } from "../lib/format";
import { ErrorState, KpiCard, PageHeader } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Dashboard() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.get<DashboardSummary>("/dashboard"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the dashboard.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** "+ New Quotation" opens a fresh draft in the builder (Screen 4). */
  async function newQuotation() {
    setCreating(true);
    try {
      const customers = await api.get<Customer[]>("/customers");
      if (customers.length === 0) throw new Error("No customers are configured.");
      const quotation = await api.post<Quotation>("/quotations", {
        customer_id: customers[0].id,
      });
      navigate(`/quotations/${quotation.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create a quotation.");
    } finally {
      setCreating(false);
    }
  }

  if (error && !data) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Sales Dashboard"
        subtitle="Central hub, links out to every module below."
        actions={
          <>
            {can("deal.create") && (
              <button
                className="btn btn--primary"
                disabled={creating}
                onClick={() => void newQuotation()}
              >
                {creating ? "Creating…" : "+ New Quotation"}
              </button>
            )}
            <button className="btn" onClick={() => navigate("/approvals")}>
              View Approvals
            </button>
          </>
        }
      />

      <div className="grid-3" style={{ marginBottom: "var(--space-5)" }}>
        <KpiCard
          label="Pending Approvals"
          value={data ? data.pending_approvals : "—"}
          caption="quotations waiting"
          onClick={() => navigate("/approvals")}
        />
        <KpiCard
          label="Open Quotations"
          value={data ? data.open_quotations : "—"}
          caption="active deals"
          onClick={() => navigate("/quotations")}
        />
        <KpiCard
          label="At-Risk Deals"
          value={data ? data.at_risk_deals : "—"}
          caption="over a discount limit"
          onClick={() => navigate("/quotations")}
        />
      </div>

      <div className="card">
        <h2 className="card__title">Recent activity</h2>
        {!data && <div className="skeleton" style={{ height: 60 }} />}
        {data && data.recent_activity.length === 0 && (
          <p className="muted">Nothing has happened yet. Create a quotation to get started.</p>
        )}
        {data && data.recent_activity.length > 0 && (
          <table className="data">
            <tbody>
              {data.recent_activity.map((entry, index) => (
                <tr key={index}>
                  <td>
                    <div className="primary-cell">{humanise(entry.action.toLowerCase())}</div>
                    <div className="sub-cell">{entry.reason ?? ""}</div>
                  </td>
                  <td className="sub-cell">{entry.user_name ?? "System"}</td>
                  <td className="sub-cell num">{dateTime(entry.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
