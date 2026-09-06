/**
 * Admin > Customers. PRD A2/A3 treat customers as master data alongside
 * products and discount tiers, so this is gated by `config.manage` — the
 * same permission as `AdminProductsList.tsx` and `AdminDiscountTiers.tsx`,
 * held by both Admin and Sales Manager — not `user.manage` (Admin-only,
 * `AdminUsersList.tsx`'s gate for accounts).
 *
 * This is the standalone path to "add a new company we can quote for" —
 * `AdminUsersList.tsx`'s invite form has its own inline "+ New customer"
 * shortcut too, but that one only exists as a side effect of inviting a
 * portal contact. A Sales Rep building a quotation needs the Customer row
 * to exist whether or not that company has a portal login yet, and a Sales
 * Manager (who can already configure discount tiers and products) had no
 * way to add one at all before this screen existed.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { AdminCustomer } from "../lib/api";
import { humanise } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

export default function AdminCustomersList() {
  const [customers, setCustomers] = useState<AdminCustomer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    code: "",
    name: "",
    tier: "bronze",
    email: "",
    phone: "",
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      setCustomers(await api.get<AdminCustomer[]>("/admin/customers"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load customers.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createCustomer() {
    setError(null);
    setNotice(null);

    if (!form.code.trim() || !form.name.trim()) {
      setError("Code and name are both required.");
      return;
    }

    setSaving(true);
    try {
      const created = await api.post<AdminCustomer>("/admin/customers", {
        code: form.code.trim(),
        name: form.name.trim(),
        tier: form.tier,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
      });
      setCustomers((current) => [...(current ?? []), created]);
      setNotice(`${created.name} added — it will now appear in the quotation builder's customer picker.`);
      setForm({ code: "", name: "", tier: "bronze", email: "", phone: "" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create that customer.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !customers) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!customers) return <TableSkeleton rows={5} cols={4} />;

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle="Every company a Sales Rep can build a quotation for. Adding one here does not create a portal login — that's a separate step on the Users screen, for when this customer needs to negotiate their own quotations online."
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
          <h2 className="card__title">Add a customer</h2>
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div className="field">
              <label className="field__label">Code</label>
              <input
                className="input"
                placeholder="ACME"
                value={form.code}
                onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Name</label>
              <input
                className="input"
                placeholder="Acme Corp"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Tier</label>
              <select
                className="select"
                value={form.tier}
                onChange={(e) => setForm((f) => ({ ...f, tier: e.target.value }))}
              >
                <option value="bronze">Bronze</option>
                <option value="silver">Silver</option>
                <option value="gold">Gold</option>
              </select>
            </div>
            <div className="field">
              <label className="field__label">Email (optional)</label>
              <input
                className="input"
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Phone (optional)</label>
              <input
                className="input"
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
              />
            </div>
            <button className="btn btn--primary" disabled={saving} onClick={() => void createCustomer()}>
              {saving ? "Adding…" : "Add customer"}
            </button>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">All customers ({customers.length})</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Code</th>
                  <th>Tier</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={c.id}>
                    <td className="primary-cell">{c.name}</td>
                    <td className="sub-cell">{c.code}</td>
                    <td>{humanise(c.tier)}</td>
                    <td>
                      <span className={`badge badge--${c.is_active ? "success" : "neutral"}`}>
                        {c.is_active ? "Active" : "Archived"}
                      </span>
                    </td>
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
