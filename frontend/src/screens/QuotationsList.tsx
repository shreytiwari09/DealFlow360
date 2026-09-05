/**
 * Screen 3 — Quotations List / Pipeline. FRONTEND.md Section 5.
 *
 * The wireframe draws this as status-grouped columns with a table toggle, so
 * both views render the same data. `under_negotiation` gets its own column
 * and its own badge — never merged with approved or pending, which is
 * Screen 3's explicit requirement.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Customer, Quotation, QuotationSummary } from "../lib/api";
import { dateTime, money } from "../lib/format";
import { EmptyState, ErrorState, PageHeader, StatusBadge, TableSkeleton } from "../components/ui";
import { useAuth } from "../lib/auth";

const STAGES = [
  { key: "draft", label: "Draft" },
  { key: "pending_approval", label: "Pending Approval" },
  { key: "approved", label: "Approved" },
  { key: "sent", label: "Sent" },
  { key: "under_negotiation", label: "Negotiation" },
  { key: "confirmed", label: "Confirmed" },
];

export default function QuotationsList() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [rows, setRows] = useState<QuotationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tableView, setTableView] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<QuotationSummary[]>("/quotations"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load quotations.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function newQuotation() {
    setCreating(true);
    try {
      const customers = await api.get<Customer[]>("/customers");
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

  const actions = (
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
      <button className="btn" onClick={() => setTableView((v) => !v)}>
        {tableView ? "Switch to Pipeline" : "Switch to Table View"}
      </button>
    </>
  );

  if (error && !rows) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Quotations"
        subtitle="Every quotation in the system, one row per quotation, click a row to open it."
        actions={actions}
      />

      {!rows && <TableSkeleton rows={5} cols={5} />}

      {rows && rows.length === 0 && (
        <EmptyState
          title="No quotations yet"
          hint="Create your first quotation to start managing your pipeline."
          action={
            can("deal.create") ? (
              <button className="btn btn--primary" onClick={() => void newQuotation()}>
                + New Quotation
              </button>
            ) : undefined
          }
        />
      )}

      {rows && rows.length > 0 && !tableView && (
        <div className="pipeline">
          {STAGES.map((stage) => {
            const inStage = rows.filter((row) => row.status === stage.key);
            return (
              <div key={stage.key} className="pipeline__col">
                <div className="pipeline__head">
                  <span className="pipeline__title">{stage.label}</span>
                  <span className="badge badge--neutral">{inStage.length}</span>
                </div>
                {inStage.map((row) => (
                  <button
                    key={row.id}
                    className="deal-card"
                    onClick={() => navigate(`/quotations/${row.id}`)}
                  >
                    <div className="deal-card__customer">{row.customer_name}</div>
                    <div className="deal-card__meta">
                      <span className="mono-num">{money(row.total_amount, row.currency)}</span>
                      <span>{row.quote_number}</span>
                    </div>
                  </button>
                ))}
                {inStage.length === 0 && <p className="sub-cell">Nothing here.</p>}
              </div>
            );
          })}
        </div>
      )}

      {rows && rows.length > 0 && tableView && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Quotation</th>
                <th>Customer</th>
                <th className="num">Amount</th>
                <th>Status</th>
                <th>Owner</th>
                <th className="num">Risk</th>
                <th className="num">Last updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className="clickable"
                  onClick={() => navigate(`/quotations/${row.id}`)}
                >
                  <td className="primary-cell">{row.quote_number}</td>
                  <td>{row.customer_name}</td>
                  <td className="num mono-num">{money(row.total_amount, row.currency)}</td>
                  <td>
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="sub-cell">{row.owner_name}</td>
                  <td className="num mono-num">{Number(row.blended_risk_score).toFixed(2)}</td>
                  <td className="num sub-cell">{dateTime(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
