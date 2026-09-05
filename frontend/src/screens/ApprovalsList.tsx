/** Screen 5 — Approvals List. FRONTEND.md Section 5. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { ApprovalSummary } from "../lib/api";
import { dateTime } from "../lib/format";
import {
  EmptyState,
  ErrorState,
  FilterChips,
  NoteBar,
  PageHeader,
  RiskBadge,
  StatusBadge,
  TableSkeleton,
} from "../components/ui";

export default function ApprovalsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ApprovalSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("pending");

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.get<ApprovalSummary[]>("/approvals"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load approvals.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    const all = rows ?? [];
    return {
      all: all.length,
      pending: all.filter((r) => r.status === "pending").length,
      approved: all.filter((r) => r.status === "approved").length,
      returned: all.filter((r) => r.status === "returned_for_revision").length,
      rejected: all.filter((r) => r.status === "rejected").length,
    };
  }, [rows]);

  const visible = useMemo(
    () => (rows ?? []).filter((row) => filter === "all" || row.status === filter),
    [rows, filter],
  );

  if (error && !rows) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Every quotation that needed review, waiting to go through discount approval."
      />

      <FilterChips
        active={filter}
        onChange={setFilter}
        options={[
          { value: "pending", label: "Pending", count: counts.pending },
          { value: "returned_for_revision", label: "Returned", count: counts.returned },
          { value: "approved", label: "Approved", count: counts.approved },
          { value: "rejected", label: "Rejected", count: counts.rejected },
          { value: "all", label: "All", count: counts.all },
        ]}
      />

      {!rows && <TableSkeleton rows={4} cols={6} />}

      {rows && visible.length === 0 && (
        <EmptyState
          title={counts.all === 0 ? "Nothing to approve" : "No approvals match this filter"}
          hint={
            counts.all === 0
              ? "Quotations appear here automatically when a discount breaches a limit."
              : "Try a different filter."
          }
        />
      )}

      {rows && visible.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Quotation</th>
                  <th>Customer</th>
                  <th>Blended Risk</th>
                  <th className="num">Score</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th className="num">Requested</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr
                    key={row.id}
                    className="clickable"
                    onClick={() => navigate(`/approvals/${row.id}`)}
                  >
                    <td className="primary-cell">{row.quote_number}</td>
                    <td>{row.customer_name}</td>
                    <td>
                      <RiskBadge band={row.risk_band} />
                    </td>
                    <td className="num mono-num">
                      {Number(row.blended_risk_score).toFixed(2)}
                    </td>
                    <td className="sub-cell">{row.current_stage ?? "—"}</td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="num sub-cell">{dateTime(row.requested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "var(--space-3)" }}>
            <NoteBar>
              Click any row to see the full approval risk breakdown and audit trail.
            </NoteBar>
          </div>
        </>
      )}
    </>
  );
}
