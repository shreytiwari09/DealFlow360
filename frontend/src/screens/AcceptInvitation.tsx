/**
 * Invitation activation — the invitee's half of `AdminUsersList.tsx`'s
 * "Invite a user" flow. Unauthenticated: the token in the URL is the
 * invitee's only credential at this point, exactly like a password-reset
 * link (`services/invitation.py`).
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../lib/api";
import type { InvitationPreview } from "../lib/api";
import { useAuth } from "../lib/auth";
import { NoteBar } from "../components/ui";

export default function AcceptInvitation() {
  const { token } = useParams<{ token: string }>();
  const { acceptInvitation } = useAuth();
  const navigate = useNavigate();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const result = await api.get<InvitationPreview>(`/auth/invitations/${token}`);
        if (!cancelled) setPreview(result);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof ApiError ? err.message : "This invitation link is invalid.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitError(null);

    if (password.length < 8) {
      setSubmitError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setSubmitError("Passwords do not match.");
      return;
    }
    if (!token) return;

    setBusy(true);
    try {
      await acceptInvitation(token, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Could not activate this account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">DealFlow360</div>
        <p className="login__tagline">Activate your account</p>

        {loadError && (
          <>
            <NoteBar tone="warning">{loadError}</NoteBar>
            <p className="muted" style={{ textAlign: "center", marginTop: "var(--space-4)" }}>
              Ask whoever invited you to send a new link. <Link to="/login">Back to login</Link>
            </p>
          </>
        )}

        {!loadError && !preview && <p className="muted">Loading…</p>}

        {preview?.already_accepted && (
          <>
            <NoteBar tone="warning">This invitation has already been used.</NoteBar>
            <p className="muted" style={{ textAlign: "center", marginTop: "var(--space-4)" }}>
              <Link to="/login">Log in instead</Link>
            </p>
          </>
        )}

        {preview?.is_expired && !preview.already_accepted && (
          <>
            <NoteBar tone="warning">
              This invitation expired on {new Date(preview.expires_at).toLocaleDateString()}.
            </NoteBar>
            <p className="muted" style={{ textAlign: "center", marginTop: "var(--space-4)" }}>
              Ask whoever invited you to send a new link. <Link to="/login">Back to login</Link>
            </p>
          </>
        )}

        {preview && !preview.already_accepted && !preview.is_expired && (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              {preview.full_name}, you've been invited as a{" "}
              <strong>{preview.role_name}</strong>
              {preview.customer_name && (
                <>
                  {" "}
                  for <strong>{preview.customer_name}</strong>
                </>
              )}
              . Choose a password to finish setting up <strong>{preview.email}</strong>.
            </p>

            <form onSubmit={submit} className="stack">
              <label className="field">
                <span className="field__label">Password</span>
                <input
                  className="input"
                  type="password"
                  value={password}
                  autoComplete="new-password"
                  minLength={8}
                  required
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="field__label">Confirm password</span>
                <input
                  className="input"
                  type="password"
                  value={confirmPassword}
                  autoComplete="new-password"
                  required
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </label>

              {submitError && <div className="field__error">{submitError}</div>}

              <button className="btn btn--primary" type="submit" disabled={busy}>
                {busy ? "Activating…" : "Activate account"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
