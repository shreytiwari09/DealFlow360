/**
 * Internal application shell — FRONTEND.md Section 2.1.
 *
 * The wireframe's top tab bar, reordered into the Style Spec's persistent
 * sidebar. That reconciliation is FRONTEND.md's own precedence rule 2.
 *
 * Nav items are filtered by permission. That is UX only: hiding "Approvals"
 * does not protect the endpoint, the backend does.
 */

import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";

interface NavEntry {
  to: string;
  label: string;
  permission?: string;
  section?: string;
  /** Not yet built — shown so the shell matches the spec, but disabled. */
  pending?: boolean;
}

const NAV: NavEntry[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/quotations", label: "Quotations" },
  { to: "/approvals", label: "Approvals" },
  { to: "/fulfillment", label: "Fulfillment" },
  { to: "/subscriptions", label: "Subscriptions", pending: true },
  { to: "/invoices", label: "Invoices", pending: true },
  { to: "/deal-health", label: "Deal Health", pending: true },
  { to: "/reports", label: "Reports", pending: true, permission: "report.view" },
  {
    to: "/admin/discount-tiers",
    label: "Discount Tiers",
    section: "Configuration",
    permission: "config.manage",
    pending: true,
  },
  { to: "/admin/products", label: "Product Catalog", permission: "user.manage", pending: true },
];

export default function InternalShell() {
  const { user, loading, signOut, can } = useAuth();
  const location = useLocation();

  if (loading) return <div className="login">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;

  // A portal user must never see the internal shell (PRD, FRONTEND.md 2.2).
  if (user.role === "customer") return <Navigate to="/portal" replace />;

  const visible = NAV.filter((entry) => !entry.permission || can(entry.permission));
  let lastSection: string | undefined;

  return (
    <div className="shell">
      <div className="shell__brand">
        <span className="shell__brand-mark">D</span>
        DealFlow360
      </div>

      <header className="shell__header">
        <span className="shell__breadcrumb">
          {visible.find((e) => location.pathname.startsWith(e.to))?.label ?? "Workspace"}
        </span>
        <div className="shell__user">
          <span>
            <span className="shell__user-name">{user.full_name}</span>
            <span className="muted"> · {user.role.replace(/_/g, " ")}</span>
          </span>
          <button type="button" className="btn btn--sm" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="shell__sidebar">
        {visible.map((entry) => {
          const heading = entry.section && entry.section !== lastSection ? entry.section : null;
          lastSection = entry.section ?? lastSection;
          return (
            <div key={entry.to}>
              {heading && <div className="nav-section">{heading}</div>}
              {entry.pending ? (
                <span
                  className="nav-item"
                  style={{ opacity: 0.45, cursor: "not-allowed" }}
                  title="Not built yet"
                >
                  {entry.label}
                </span>
              ) : (
                <NavLink
                  to={entry.to}
                  className={({ isActive }) =>
                    isActive ? "nav-item nav-item--active" : "nav-item"
                  }
                >
                  {entry.label}
                </NavLink>
              )}
            </div>
          );
        })}
      </nav>

      <main className="shell__main">
        <Outlet />
      </main>
    </div>
  );
}
