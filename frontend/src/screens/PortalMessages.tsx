/**
 * Portal "Messages" (FRONTEND.md Screen 11's top-bar nav item — previously
 * disabled with no defined screen behind it). A read-only, cross-quotation
 * history of the customer's own past requests/counter-offers — the same
 * audit-trail data each quotation's own comment thread already shows
 * (Locked Business Rules #8b), aggregated here instead of scoped to one
 * quote. There is no reply-from-rep capability yet, so this is one-directional
 * on purpose rather than pretending to be a live conversation it is not.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { PortalMessage } from "../lib/api";
import { dateTime } from "../lib/format";
import { EmptyState, ErrorState, PageHeader, TableSkeleton } from "../components/ui";

export default function PortalMessages() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<PortalMessage[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMessages(await api.get<PortalMessage[]>("/portal/messages"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your messages.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !messages) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <>
      <PageHeader
        title="Messages"
        subtitle="Every request and counter-offer you've sent, across all your quotations."
      />

      {!messages && <TableSkeleton rows={3} cols={3} />}

      {messages && messages.length === 0 && (
        <EmptyState
          title="Nothing here yet"
          hint="A message appears here once you submit a request or counter-offer on a quotation."
        />
      )}

      {messages && messages.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Quotation</th>
                  <th>Message</th>
                  <th className="num">Sent</th>
                </tr>
              </thead>
              <tbody>
                {messages.map((m) => (
                  <tr
                    key={`${m.quotation_id}-${m.created_at}`}
                    className="clickable"
                    onClick={() => navigate(`/portal/quotations/${m.quotation_id}`)}
                  >
                    <td className="primary-cell">{m.quote_number}</td>
                    <td>{m.message}</td>
                    <td className="num sub-cell">{dateTime(m.created_at)}</td>
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
