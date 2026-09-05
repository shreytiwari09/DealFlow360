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
import PortalShell from "./layouts/PortalShell";
import Login from "./screens/Login";
import Register from "./screens/Register";
import Dashboard from "./screens/Dashboard";
import QuotationsList from "./screens/QuotationsList";
import QuotationDetail from "./screens/QuotationDetail";
import ApprovalsList from "./screens/ApprovalsList";
import ApprovalDetail from "./screens/ApprovalDetail";
import FulfillmentList from "./screens/FulfillmentList";
import FulfillmentDetail from "./screens/FulfillmentDetail";
import SubscriptionsList from "./screens/SubscriptionsList";
import SubscriptionDetail from "./screens/SubscriptionDetail";
import InvoicesList from "./screens/InvoicesList";
import InvoiceDetail from "./screens/InvoiceDetail";
import PortalQuotationsList from "./screens/PortalQuotationsList";
import PortalQuotationDetail from "./screens/PortalQuotationDetail";
import DealHealthDashboard from "./screens/DealHealthDashboard";
import ReportsScreen from "./screens/ReportsScreen";
import AdminDiscountTiers from "./screens/AdminDiscountTiers";
import AdminProductsList from "./screens/AdminProductsList";
import AdminProductDetail from "./screens/AdminProductDetail";
import "./styles/tokens.css";
import "./styles/app.css";

/** Sends an already-signed-in user to the right shell for their role. */
function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="login">Loading…</div>;
  if (user) {
    return <Navigate to={user.role === "customer" ? "/portal/quotations" : "/dashboard"} replace />;
  }
  return <Login />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/register" element={<Register />} />
          {/* A customer landing on the bare /portal (an old bookmark, or the
              redirect above) goes straight to their list — there is no
              standalone /portal screen of its own. */}
          <Route path="/portal" element={<Navigate to="/portal/quotations" replace />} />

          <Route element={<InternalShell />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/quotations" element={<QuotationsList />} />
            <Route path="/quotations/:id" element={<QuotationDetail />} />
            <Route path="/approvals" element={<ApprovalsList />} />
            <Route path="/approvals/:id" element={<ApprovalDetail />} />
            <Route path="/fulfillment" element={<FulfillmentList />} />
            <Route path="/fulfillment/:id" element={<FulfillmentDetail />} />
            <Route path="/subscriptions" element={<SubscriptionsList />} />
            <Route path="/subscriptions/:id" element={<SubscriptionDetail />} />
            <Route path="/invoices" element={<InvoicesList />} />
            <Route path="/invoices/:id" element={<InvoiceDetail />} />
            <Route path="/deal-health" element={<DealHealthDashboard />} />
            <Route path="/reports" element={<ReportsScreen />} />
            <Route path="/admin/discount-tiers" element={<AdminDiscountTiers />} />
            <Route path="/admin/products" element={<AdminProductsList />} />
            <Route path="/admin/products/:id" element={<AdminProductDetail />} />
          </Route>

          <Route element={<PortalShell />}>
            <Route path="/portal/quotations" element={<PortalQuotationsList />} />
            <Route path="/portal/quotations/:id" element={<PortalQuotationDetail />} />
          </Route>

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
