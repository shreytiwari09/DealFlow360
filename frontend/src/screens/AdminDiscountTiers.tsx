/**
 * Screen 18 — Discount Tiers and Approval Chain Setup. FRONTEND.md Section 5, PRD A3.
 *
 * FRONTEND.md's wireframe draws "Tier Discount Ceilings" and "Category
 * Discount Ceilings" as two separate tables. The real ceiling has always
 * been per (tier, category) PAIR (Locked Business Rules #1 and #6) — showing
 * it as two independent tables would misrepresent how a ceiling is actually
 * looked up, so this renders the one matrix the backend actually has:
 * categories down the side, tiers across the top.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ApprovalChainRow, DiscountTierRow, RoleOption } from "../lib/api";
import { ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

const TIERS = ["bronze", "silver", "gold"];

export default function AdminDiscountTiers() {
  const [tiers, setTiers] = useState<DiscountTierRow[] | null>(null);
  const [chains, setChains] = useState<ApprovalChainRow[] | null>(null);
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<number, string>>({});

  const [newChain, setNewChain] = useState({
    min_score: "",
    max_score: "",
    required_role_id: "",
    step_order: "1",
    label: "",
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [t, c, r] = await Promise.all([
        api.get<DiscountTierRow[]>("/admin/discount-tiers"),
        api.get<ApprovalChainRow[]>("/admin/approval-chains"),
        api.get<RoleOption[]>("/admin/roles"),
      ]);
      setTiers(t);
      setChains(c);
      setRoles(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load configuration.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveCeiling(tier: DiscountTierRow) {
    const value = editValues[tier.id];
    if (value === undefined || value === tier.max_discount_percent) return;
    setBusyId(tier.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.put<DiscountTierRow>(`/admin/discount-tiers/${tier.id}`, {
        max_discount_percent: Number(value),
      });
      setTiers((current) => current?.map((t) => (t.id === updated.id ? updated : t)) ?? null);
      setNotice("Configuration saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save that ceiling.");
    } finally {
      setBusyId(null);
    }
  }

  async function addChain() {
    if (!newChain.min_score || !newChain.required_role_id) {
      setError("Min score and required role are needed to add a band.");
      return;
    }
    setError(null);
    try {
      const created = await api.post<ApprovalChainRow>("/admin/approval-chains", {
        min_score: Number(newChain.min_score),
        max_score: newChain.max_score ? Number(newChain.max_score) : null,
        required_role_id: Number(newChain.required_role_id),
        step_order: Number(newChain.step_order) || 1,
        label: newChain.label || null,
      });
      setChains((current) => [...(current ?? []), created]);
      setNewChain({ min_score: "", max_score: "", required_role_id: "", step_order: "1", label: "" });
      setNotice("Band added.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that band.");
    }
  }

  async function toggleChainActive(chain: ApprovalChainRow) {
    setBusyId(chain.id);
    setError(null);
    try {
      const updated = await api.put<ApprovalChainRow>(`/admin/approval-chains/${chain.id}`, {
        min_score: Number(chain.min_score),
        max_score: chain.max_score ? Number(chain.max_score) : null,
        step_order: chain.step_order,
        label: chain.label,
        is_active: !chain.is_active,
      });
      setChains((current) => current?.map((c) => (c.id === updated.id ? updated : c)) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update that band.");
    } finally {
      setBusyId(null);
    }
  }

  if (error && !tiers) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!tiers || !chains) return <TableSkeleton rows={5} cols={4} />;

  const categories = [...new Map(tiers.map((t) => [t.category_id, t.category_name])).entries()];

  return (
    <>
      <PageHeader
        title="Discount tiers and approval chains"
        subtitle="When a quote combines different ceilings, the system computes a blended risk score and routes to the highest required level."
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
          <h2 className="card__title">Discount ceiling matrix</h2>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Category</th>
                  {TIERS.map((tier) => (
                    <th key={tier} className="num" style={{ textTransform: "capitalize" }}>
                      {tier}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {categories.map(([categoryId, categoryName]) => (
                  <tr key={categoryId}>
                    <td className="primary-cell">{categoryName}</td>
                    {TIERS.map((tier) => {
                      const row = tiers.find(
                        (t) => t.category_id === categoryId && t.customer_tier === tier,
                      );
                      if (!row) return <td key={tier} className="num muted">—</td>;
                      return (
                        <td key={tier} className="num">
                          <input
                            className="input input--num"
                            type="number"
                            min="0"
                            max="100"
                            step="0.5"
                            value={editValues[row.id] ?? row.max_discount_percent}
                            onChange={(e) =>
                              setEditValues((current) => ({ ...current, [row.id]: e.target.value }))
                            }
                            onBlur={() => void saveCeiling(row)}
                            disabled={busyId === row.id}
                          />
                          %
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "var(--space-3)" }}>
            <NoteBar>Edit a cell and tab or click away to save — changes apply immediately.</NoteBar>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">Discount range → approval chain</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            The single-line rule (any one line more than 15 points over its own limit forces
            Finance regardless of the blended score) is a fixed guard rail, not configurable here.
          </p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th className="num">Min score</th>
                  <th className="num">Max score</th>
                  <th className="num">Step</th>
                  <th>Required role</th>
                  <th>Label</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {chains.map((chain) => (
                  <tr key={chain.id}>
                    <td className="num mono-num">{Number(chain.min_score)}</td>
                    <td className="num mono-num">{chain.max_score ? Number(chain.max_score) : "∞"}</td>
                    <td className="num mono-num">{chain.step_order}</td>
                    <td>{chain.required_role_name}</td>
                    <td className="sub-cell">{chain.label ?? "—"}</td>
                    <td>
                      <span className={`badge badge--${chain.is_active ? "success" : "neutral"}`}>
                        {chain.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn--sm"
                        disabled={busyId === chain.id}
                        onClick={() => void toggleChainActive(chain)}
                      >
                        {chain.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="card__title" style={{ marginTop: "var(--space-4)" }}>
            Add a band
          </h3>
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div className="field">
              <label className="field__label">Min score</label>
              <input
                className="input input--num"
                type="number"
                value={newChain.min_score}
                onChange={(e) => setNewChain((c) => ({ ...c, min_score: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Max score (blank = ∞)</label>
              <input
                className="input input--num"
                type="number"
                value={newChain.max_score}
                onChange={(e) => setNewChain((c) => ({ ...c, max_score: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Step</label>
              <input
                className="input input--num"
                type="number"
                min="1"
                value={newChain.step_order}
                onChange={(e) => setNewChain((c) => ({ ...c, step_order: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Required role</label>
              <select
                className="select"
                value={newChain.required_role_id}
                onChange={(e) => setNewChain((c) => ({ ...c, required_role_id: e.target.value }))}
              >
                <option value="">Choose…</option>
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field__label">Label (optional)</label>
              <input
                className="input"
                value={newChain.label}
                onChange={(e) => setNewChain((c) => ({ ...c, label: e.target.value }))}
              />
            </div>
            <button className="btn btn--primary" onClick={() => void addChain()}>
              Add band
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
