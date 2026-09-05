/**
 * Screen 17 — Product Detail (Product and Pricelist). FRONTEND.md Section 5, PRD A2.
 *
 * Variants and Pricelists tables from the wireframe are not built this
 * round — General Info (create/edit) is the part PRD A2 actually gates the
 * builder's product picker on. Noted as a follow-up, not silently dropped.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { AdminProduct, ProductCategoryRow } from "../lib/api";
import { ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

const isNew = (id: string | undefined) => !id || id === "new";

export default function AdminProductDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const creating = isNew(id);

  const [categories, setCategories] = useState<ProductCategoryRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    sku: "",
    name: "",
    description: "",
    category_id: "",
    unit: "unit",
    list_price: "",
    cost_price: "",
    tax_rate: "0",
    item_type: "one_time",
    is_promoted: false,
    is_active: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cats = await api.get<ProductCategoryRow[]>("/admin/categories");
      setCategories(cats);
      if (!creating && id) {
        const product = await api.get<AdminProduct>(`/admin/products/${id}`);
        setForm({
          sku: product.sku,
          name: product.name,
          description: product.description ?? "",
          category_id: String(product.category_id),
          unit: product.unit,
          list_price: product.list_price,
          cost_price: product.cost_price,
          tax_rate: product.tax_rate,
          item_type: product.item_type,
          is_promoted: product.is_promoted,
          is_active: product.is_active,
        });
      } else if (cats.length > 0) {
        setForm((f) => ({ ...f, category_id: String(cats[0].id) }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load this product.");
    } finally {
      setLoading(false);
    }
  }, [id, creating]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (creating) {
        const created = await api.post<AdminProduct>("/admin/products", {
          sku: form.sku,
          name: form.name,
          description: form.description || null,
          category_id: Number(form.category_id),
          unit: form.unit,
          list_price: Number(form.list_price) || 0,
          cost_price: Number(form.cost_price) || 0,
          tax_rate: Number(form.tax_rate) || 0,
          item_type: form.item_type,
          is_promoted: form.is_promoted,
        });
        navigate(`/admin/products/${created.id}`, { replace: true });
      } else {
        await api.put<AdminProduct>(`/admin/products/${id}`, {
          name: form.name,
          description: form.description || null,
          category_id: Number(form.category_id),
          unit: form.unit,
          list_price: Number(form.list_price) || 0,
          cost_price: Number(form.cost_price) || 0,
          tax_rate: Number(form.tax_rate) || 0,
          is_promoted: form.is_promoted,
          is_active: form.is_active,
        });
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not save this product.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <TableSkeleton rows={4} cols={2} />;
  if (error && !creating && !form.name) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }

  return (
    <>
      <PageHeader
        title={creating ? "New Product" : form.name}
        subtitle="General info. Recurring order billing begins at the start of the next period."
        actions={
          <>
            <button className="btn" onClick={() => navigate("/admin/products")}>
              Back to catalog
            </button>
            <button className="btn btn--primary" disabled={saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save"}
            </button>
          </>
        }
      />

      {error && (
        <div style={{ marginBottom: "var(--space-4)" }}>
          <NoteBar tone="warning">{error}</NoteBar>
        </div>
      )}

      <div className="card">
        <h2 className="card__title">General Info</h2>
        <div className="stack" style={{ gap: "var(--space-3)", maxWidth: 480 }}>
          <div className="field">
            <label className="field__label">SKU</label>
            <input
              className="input"
              value={form.sku}
              disabled={!creating}
              onChange={(e) => setForm((f) => ({ ...f, sku: e.target.value }))}
            />
          </div>
          <div className="field">
            <label className="field__label">Product name</label>
            <input
              className="input"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="field">
            <label className="field__label">Category</label>
            <select
              className="select"
              value={form.category_id}
              onChange={(e) => setForm((f) => ({ ...f, category_id: e.target.value }))}
            >
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="row" style={{ gap: "var(--space-3)" }}>
            <div className="field">
              <label className="field__label">List price</label>
              <input
                className="input input--num"
                type="number"
                value={form.list_price}
                onChange={(e) => setForm((f) => ({ ...f, list_price: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Cost price</label>
              <input
                className="input input--num"
                type="number"
                value={form.cost_price}
                onChange={(e) => setForm((f) => ({ ...f, cost_price: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="field__label">Tax %</label>
              <input
                className="input input--num"
                type="number"
                value={form.tax_rate}
                onChange={(e) => setForm((f) => ({ ...f, tax_rate: e.target.value }))}
              />
            </div>
          </div>
          <div className="field">
            <label className="field__label">Unit</label>
            <input
              className="input"
              value={form.unit}
              onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))}
            />
          </div>
          <div className="field">
            <label className="field__label">Description</label>
            <textarea
              className="textarea"
              rows={3}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>

          {creating && (
            <div className="field">
              <label className="field__label">Subscription?</label>
              <select
                className="select"
                value={form.item_type}
                onChange={(e) => setForm((f) => ({ ...f, item_type: e.target.value }))}
              >
                <option value="one_time">No — one-time product</option>
                <option value="subscription">Yes — subscription</option>
              </select>
            </div>
          )}
          {!creating && (
            <NoteBar>
              Whether this is a one-time or subscription product cannot be changed after
              creation — existing quotation lines have already snapshotted it.
            </NoteBar>
          )}

          <label className="row" style={{ gap: "var(--space-2)" }}>
            <input
              type="checkbox"
              checked={form.is_promoted}
              onChange={(e) => setForm((f) => ({ ...f, is_promoted: e.target.checked }))}
            />
            Promoted (ranks higher in upsell suggestions)
          </label>

          {!creating && (
            <label className="row" style={{ gap: "var(--space-2)" }}>
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
              />
              Active (uncheck to archive — never hard-deleted)
            </label>
          )}
        </div>
      </div>
    </>
  );
}
