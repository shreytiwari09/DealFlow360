/** Screen 16 — Product Catalog. FRONTEND.md Section 5, PRD A2. */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { AdminProduct } from "../lib/api";
import { humanise, money } from "../lib/format";
import { ErrorState, PageHeader, TableSkeleton } from "../components/ui";

export default function AdminProductsList() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<AdminProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setProducts(await api.get<AdminProduct[]>("/admin/products"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the product catalogue.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !products) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!products) return <TableSkeleton rows={5} cols={7} />;

  const activeCount = products.filter((p) => p.is_active).length;
  const archivedCount = products.length - activeCount;

  return (
    <>
      <PageHeader
        title="Product Catalog"
        subtitle="Every product, variant and price list in one place."
        actions={
          <button className="btn btn--primary" onClick={() => navigate("/admin/products/new")}>
            + New Product
          </button>
        }
      />

      <div className="grid-3" style={{ marginBottom: "var(--space-4)" }}>
        <div className="card">
          <div className="kpi__label">Total Products</div>
          <div className="kpi__value">{products.length}</div>
          <div className="kpi__caption">
            {activeCount} active, {archivedCount} archived
          </div>
        </div>
        <div className="card">
          <div className="kpi__label">Subscription products</div>
          <div className="kpi__value">
            {products.filter((p) => p.item_type === "subscription").length}
          </div>
        </div>
        <div className="card">
          <div className="kpi__label">Promoted</div>
          <div className="kpi__value">{products.filter((p) => p.is_promoted).length}</div>
        </div>
      </div>

      <div className="card">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Product name</th>
                <th>Category</th>
                <th className="num">Price</th>
                <th>Unit</th>
                <th className="num">Tax</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr
                  key={p.id}
                  className="clickable"
                  onClick={() => navigate(`/admin/products/${p.id}`)}
                >
                  <td className="primary-cell">
                    {p.name}
                    <div className="sub-cell">{p.sku}</div>
                  </td>
                  <td>{p.category_name}</td>
                  <td className="num mono-num">{money(p.list_price)}</td>
                  <td className="sub-cell">{humanise(p.unit)}</td>
                  <td className="num mono-num">{Number(p.tax_rate)}%</td>
                  <td>
                    <span className={`badge badge--${p.is_active ? "success" : "neutral"}`}>
                      {p.is_active ? "Active" : "Archived"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
