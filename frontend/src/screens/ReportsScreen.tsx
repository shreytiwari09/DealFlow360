/** Screen 15 — Admin / Reporting Dashboard. FRONTEND.md Section 5, PRD A7. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ReportResult } from "../lib/api";
import { dateTime, humanise, money } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";

const STATUSES = [
  "draft",
  "pending_approval",
  "approved",
  "rejected",
  "sent",
  "under_negotiation",
  "confirmed",
  "fulfilled",
  "cancelled",
];

export default function ReportsScreen() {
  const [report, setReport] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"xlsx" | "pdf" | null>(null);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [status, setStatus] = useState("");

  const query = useCallback(() => {
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (status) params.set("status", status);
    return params.toString();
  }, [dateFrom, dateTo, status]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setReport(await api.get<ReportResult>(`/reports?${query()}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the report.");
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  async function exportAs(format: "xlsx" | "pdf") {
    setExporting(format);
    setError(null);
    try {
      await api.download(
        `/reports/export?format=${format}&${query()}`,
        `dealflow360-report.${format}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export the report.");
    } finally {
      setExporting(null);
    }
  }

  if (error && !report) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Sales trends, filtered by period, status and more."
        actions={
          <>
            <button
              className="btn"
              disabled={exporting !== null}
              onClick={() => void exportAs("xlsx")}
            >
              {exporting === "xlsx" ? "Exporting…" : "Export XLS"}
            </button>
            <button
              className="btn"
              disabled={exporting !== null}
              onClick={() => void exportAs("pdf")}
            >
              {exporting === "pdf" ? "Exporting…" : "Export PDF"}
            </button>
          </>
        }
      />

      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="card" style={{ marginBottom: "var(--space-4)" }}>
        <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field">
            <label className="field__label">From</label>
            <input
              className="input"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field__label">To</label>
            <input
              className="input"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field__label">Approval status</label>
            <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanise(s)}
                </option>
              ))}
            </select>
          </div>
          <button className="btn btn--primary" onClick={() => void load()}>
            Apply filters
          </button>
        </div>
      </div>

      {!report ? (
        <TableSkeleton rows={5} cols={6} />
      ) : (
        <div className="stack">
          <div className="grid-3">
            <div className="card">
              <div className="kpi__label">Quotations</div>
              <div className="kpi__value">{report.count}</div>
            </div>
            <div className="card">
              <div className="kpi__label">Total value</div>
              <div className="kpi__value">{money(report.total_amount)}</div>
            </div>
            <div className="card">
              <div className="kpi__label">Total discount</div>
              <div className="kpi__value">{money(report.total_discount)}</div>
            </div>
          </div>

          <div className="card">
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Quote #</th>
                    <th>Customer</th>
                    <th>Owner</th>
                    <th>Status</th>
                    <th className="num">Total</th>
                    <th className="num">Discount</th>
                    <th className="num">Risk</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="muted" style={{ textAlign: "center" }}>
                        No quotations match these filters.
                      </td>
                    </tr>
                  )}
                  {report.rows.map((row) => (
                    <tr key={row.quote_number}>
                      <td className="primary-cell">{row.quote_number}</td>
                      <td>{row.customer_name}</td>
                      <td>{row.owner_name}</td>
                      <td>
                        <StatusBadge status={row.status} />
                      </td>
                      <td className="num mono-num">{money(row.total_amount)}</td>
                      <td className="num mono-num">{money(row.discount_amount)}</td>
                      <td className="num mono-num">{Number(row.blended_risk_score).toFixed(2)}</td>
                      <td className="sub-cell">{dateTime(row.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
