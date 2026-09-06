/**
 * Admin > Users. PRD A1 ("After login, internal users can access backend
 * configuration") and Locked Business Rules #5.
 *
 * There is deliberately no "set a password" field anywhere on this screen.
 * An Admin provisions the account and hands the invitee a one-time link;
 * the invitee is the only person who ever chooses their own password — the
 * same reasoning as a "forgot password" flow, applied to account creation
 * instead of recovery. See `services/invitation.py`'s module docstring for
 * why this replaces a direct "create with password" form.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { AdminCustomer, AdminUser, InviteUserResult, RoleOption } from "../lib/api";
import { dateTime, humanise } from "../lib/format";
import { ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

const CUSTOMER_ROLE_CODE = "customer";

export default function AdminUsersList() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [customers, setCustomers] = useState<AdminCustomer[] | null>(null);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({ email: "", full_name: "", role_id: "", customer_id: "" });
  const [showNewCustomer, setShowNewCustomer] = useState(false);
  const [newCustomer, setNewCustomer] = useState({ code: "", name: "", tier: "bronze" });
  const [inviting, setInviting] = useState(false);
  const [lastInvite, setLastInvite] = useState<InviteUserResult | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [u, c, r] = await Promise.all([
        api.get<AdminUser[]>("/admin/users"),
        api.get<AdminCustomer[]>("/admin/customers"),
        api.get<RoleOption[]>("/admin/roles"),
      ]);
      setUsers(u);
      setCustomers(c);
      setRoles(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load users.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedRole = roles.find((r) => String(r.id) === form.role_id);
  const isCustomerRole = selectedRole?.code === CUSTOMER_ROLE_CODE;

  async function createCustomerInline(): Promise<number | null> {
    if (!newCustomer.code.trim() || !newCustomer.name.trim()) {
      setError("A new customer needs both a code and a name.");
      return null;
    }
    try {
      const created = await api.post<AdminCustomer>("/admin/customers", {
        code: newCustomer.code.trim(),
        name: newCustomer.name.trim(),
        tier: newCustomer.tier,
      });
      setCustomers((current) => [...(current ?? []), created]);
      return created.id;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create that customer.");
      return null;
    }
  }

  async function invite() {
    setError(null);
    setLastInvite(null);
    setCopied(false);

    if (!form.email.trim() || !form.full_name.trim() || !form.role_id) {
      setError("Email, name and role are all required to invite someone.");
      return;
    }

    setInviting(true);
    try {
      let customerId: number | null = null;
      if (isCustomerRole) {
        if (showNewCustomer) {
          customerId = await createCustomerInline();
          if (customerId === null) return;
        } else if (form.customer_id) {
          customerId = Number(form.customer_id);
        } else {
          setError("A portal account must be linked to a customer.");
          return;
        }
      }

      const result = await api.post<InviteUserResult>("/admin/users/invite", {
        email: form.email.trim(),
        full_name: form.full_name.trim(),
        role_id: Number(form.role_id),
        customer_id: customerId,
      });

      setUsers((current) => [...(current ?? []), result.user]);
      setLastInvite(result);
      setForm({ email: "", full_name: "", role_id: "", customer_id: "" });
      setShowNewCustomer(false);
      setNewCustomer({ code: "", name: "", tier: "bronze" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send that invitation.");
    } finally {
      setInviting(false);
    }
  }

  async function copyLink() {
    if (!lastInvite) return;
    try {
      await navigator.clipboard.writeText(lastInvite.invite_url);
      setCopied(true);
    } catch {
      // Clipboard access can be denied (permissions, non-HTTPS context) —
      // the link is still on screen to select and copy by hand.
    }
  }

  if (error && !users) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!users || !customers) return <TableSkeleton rows={5} cols={5} />;

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Every account — internal and portal — is created here first, then activated by the person it belongs to."
      />

      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="stack">
        <div className="card">
          <h2 className="card__title">Invite a user</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Nobody but the invitee ever sets their password — you send them a one-time link, and
            they choose it themselves when they open it. This is also how a portal (customer)
            login gets created: it must always be linked to one specific customer, which a
            self-service signup could never safely be trusted to pick for itself.
          </p>

          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div className="field">
              <label className="field__label">Full name</label>
              <input
                className="input"
                value={form.full_name}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Email</label>
              <input
                className="input"
                type="email"
                placeholder="name@company.com"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Role</label>
              <select
                className="select"
                value={form.role_id}
                onChange={(e) =>
                  setForm((f) => ({ ...f, role_id: e.target.value, customer_id: "" }))
                }
              >
                <option value="">Choose…</option>
                {roles
                  .filter((r) => r.code !== "admin")
                  .map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
              </select>
            </div>

            {isCustomerRole && !showNewCustomer && (
              <div className="field">
                <label className="field__label">Customer</label>
                <select
                  className="select"
                  value={form.customer_id}
                  onChange={(e) => setForm((f) => ({ ...f, customer_id: e.target.value }))}
                >
                  <option value="">Choose…</option>
                  {customers
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.code})
                      </option>
                    ))}
                </select>
              </div>
            )}

            {isCustomerRole && (
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => setShowNewCustomer((v) => !v)}
              >
                {showNewCustomer ? "Use an existing customer" : "+ New customer"}
              </button>
            )}

            <button className="btn btn--primary" disabled={inviting} onClick={() => void invite()}>
              {inviting ? "Sending…" : "Send invitation"}
            </button>
          </div>

          {isCustomerRole && showNewCustomer && (
            <div
              className="row"
              style={{ gap: "var(--space-3)", flexWrap: "wrap", marginTop: "var(--space-3)" }}
            >
              <div className="field">
                <label className="field__label">Customer code</label>
                <input
                  className="input"
                  value={newCustomer.code}
                  onChange={(e) => setNewCustomer((c) => ({ ...c, code: e.target.value }))}
                />
              </div>
              <div className="field">
                <label className="field__label">Customer name</label>
                <input
                  className="input"
                  value={newCustomer.name}
                  onChange={(e) => setNewCustomer((c) => ({ ...c, name: e.target.value }))}
                />
              </div>
              <div className="field">
                <label className="field__label">Tier</label>
                <select
                  className="select"
                  value={newCustomer.tier}
                  onChange={(e) => setNewCustomer((c) => ({ ...c, tier: e.target.value }))}
                >
                  <option value="bronze">Bronze</option>
                  <option value="silver">Silver</option>
                  <option value="gold">Gold</option>
                </select>
              </div>
            </div>
          )}

          {lastInvite && (
            <div style={{ marginTop: "var(--space-4)" }}>
              <NoteBar>
                Invitation created for <strong>{lastInvite.user.email}</strong>. There is no email
                sending in this project — copy this link and send it to them yourself. It expires{" "}
                {dateTime(lastInvite.expires_at)}.
              </NoteBar>
              <div className="row" style={{ gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
                <input className="input" readOnly value={lastInvite.invite_url} />
                <button type="button" className="btn btn--sm" onClick={() => void copyLink()}>
                  {copied ? "Copied!" : "Copy link"}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="card__title">All users</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Customer</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="primary-cell">{u.full_name}</td>
                    <td className="sub-cell">{u.email}</td>
                    <td>{u.role_name}</td>
                    <td className="sub-cell">{u.customer_name ?? "—"}</td>
                    <td>
                      {u.is_active ? (
                        <span className="badge badge--success">Active</span>
                      ) : u.has_password ? (
                        <span className="badge badge--neutral">Deactivated</span>
                      ) : (
                        <span className="badge badge--warning">Invited — not yet activated</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">Customers</h2>
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
