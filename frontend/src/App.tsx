/**
 * Route map — FRONTEND.md Section 10.
 *
 * Only the routes that are actually built are registered. Screens 7-18 have
 * sidebar entries marked "not built yet" rather than routes that would render
 * an empty shell — a nav item that leads nowhere is worse than one that says
 * so honestly.
 *
 * Route guards here are UX only. The backend rejects unauthorized calls
 * regardless of what the router shows (SECURITY_SPEC.md Section 4).
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import InternalShell from "./layouts/InternalShell";
import Login from "./screens/Login";
import Dashboard from "./screens/Dashboard";
import QuotationsList from "./screens/QuotationsList";
import QuotationDetail from "./screens/QuotationDetail";
import ApprovalsList from "./screens/ApprovalsList";
import ApprovalDetail from "./screens/ApprovalDetail";
import FulfillmentList from "./screens/FulfillmentList";
import FulfillmentDetail from "./screens/FulfillmentDetail";
import "./styles/tokens.css";
import "./styles/app.css";

/** Sends an already-signed-in user to the right shell for their role. */
function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="login">Loading…</div>;
  if (user) return <Navigate to={user.role === "customer" ? "/portal" : "/dashboard"} replace />;
  return <Login />;
}

/**
 * The customer portal shell (FRONTEND.md Section 2.2) is Phase 3 step 7 and
 * is not built. Portal users are told so rather than being dropped into the
 * internal shell, which they must never see.
 */
function PortalPlaceholder() {
  const { user, signOut } = useAuth();
  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">DealFlow360</div>
        <p className="login__tagline">Customer portal</p>
        <p>
          Signed in as <strong>{user?.full_name}</strong>
          {user?.customer_name ? ` (${user.customer_name})` : ""}.
        </p>
        <p className="muted">
          The negotiation screen is not built yet. It is a separate, restricted view — not
          the internal workspace — so there is deliberately nothing here to fall back to.
        </p>
        <button className="btn" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/portal" element={<PortalPlaceholder />} />

          <Route element={<InternalShell />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/quotations" element={<QuotationsList />} />
            <Route path="/quotations/:id" element={<QuotationDetail />} />
            <Route path="/approvals" element={<ApprovalsList />} />
            <Route path="/approvals/:id" element={<ApprovalDetail />} />
            <Route path="/fulfillment" element={<FulfillmentList />} />
            <Route path="/fulfillment/:id" element={<FulfillmentDetail />} />
          </Route>

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
