/**
 * Customer portal shell — FRONTEND.md Section 2.2.
 *
 * A completely separate shell, matching the wireframe's own separate top bar
 * on Screen 11 (`My Quotations | Messages | Profile`). No sidebar, no internal
 * navigation, no route into the internal workspace — the PRD's technical
 * guidelines require this to be "a real, separate, restricted view, not just
 * another internal screen with a different label", and a shared shell with
 * items hidden would be exactly the latter.
 *
 * `Messages` and `Profile` were nav labels in the wireframe with no screen
 * content specified anywhere; both are now real, built from what the backend
 * actually has rather than an invented spec (`PortalMessages.tsx`,
 * `PortalProfile.tsx`).
 */

import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";

export default function PortalShell() {
  const { user, loading, signOut } = useAuth();
  const location = useLocation();

  if (loading) return <div className="login">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;

  // An internal user has no business in the customer shell, just as a
  // customer has none in the internal one. The backend enforces this too:
  // every /portal route requires a `portal.*` permission no internal role
  // holds. This is only the UX half.
  if (user.role !== "customer") return <Navigate to="/dashboard" replace />;

  return (
    <div className="portal">
      <header className="portal__bar">
        <div className="portal__brand">DealFlow360</div>
        <nav className="portal__nav">
          <NavLink
            to="/portal/quotations"
            className={({ isActive }) =>
              isActive ? "portal__link portal__link--active" : "portal__link"
            }
          >
            My Quotations
          </NavLink>
          <NavLink
            to="/portal/messages"
            className={({ isActive }) =>
              isActive ? "portal__link portal__link--active" : "portal__link"
            }
          >
            Messages
          </NavLink>
          <NavLink
            to="/portal/profile"
            className={({ isActive }) =>
              isActive ? "portal__link portal__link--active" : "portal__link"
            }
          >
            Profile
          </NavLink>
        </nav>
        <div className="portal__user">
          <span className="muted">{user.customer_name ?? user.full_name}</span>
          <button type="button" className="btn btn--sm" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      <main className="portal__main">
        <Outlet />
      </main>
    </div>
  );
}
