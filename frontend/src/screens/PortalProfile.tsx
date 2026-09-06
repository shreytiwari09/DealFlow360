/**
 * Portal "Profile" (FRONTEND.md Screen 11's top-bar nav item — previously
 * disabled with no defined screen behind it). Read-only account details plus
 * a password change; nothing here lets the customer edit their own company
 * record (name/tier/etc.) — that stays Admin/Sales-Manager master data.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { PortalProfile as PortalProfileData } from "../lib/api";
import { ErrorState, NoteBar, PageHeader, TableSkeleton } from "../components/ui";

export default function PortalProfile() {
  const [profile, setProfile] = useState<PortalProfileData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setProfile(await api.get<PortalProfileData>("/portal/profile"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your profile.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setFormError(null);
    setSuccess(false);

    if (newPassword.length < 8) {
      setFormError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setFormError("New passwords do not match.");
      return;
    }

    setSaving(true);
    try {
      await api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not change your password.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !profile) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!profile) return <TableSkeleton rows={3} cols={2} />;

  return (
    <>
      <PageHeader title="Profile" subtitle="Your account details and password." />

      <div className="stack">
        <div className="card">
          <h2 className="card__title">Account</h2>
          <div className="stack" style={{ gap: "var(--space-2)" }}>
            <div>
              <span className="field__label">Name</span>
              <div>{profile.full_name}</div>
            </div>
            <div>
              <span className="field__label">Email</span>
              <div>{profile.email}</div>
            </div>
            <div>
              <span className="field__label">Company</span>
              <div>
                {profile.customer_name} ({profile.customer_code}) ·{" "}
                {profile.customer_tier.charAt(0).toUpperCase() + profile.customer_tier.slice(1)}{" "}
                tier
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">Change password</h2>
          <form onSubmit={changePassword} className="stack" style={{ maxWidth: 360 }}>
            <label className="field">
              <span className="field__label">Current password</span>
              <input
                className="input"
                type="password"
                value={currentPassword}
                autoComplete="current-password"
                required
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">New password</span>
              <input
                className="input"
                type="password"
                value={newPassword}
                autoComplete="new-password"
                minLength={8}
                required
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">Confirm new password</span>
              <input
                className="input"
                type="password"
                value={confirmPassword}
                autoComplete="new-password"
                required
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </label>

            {formError && <div className="field__error">{formError}</div>}
            {success && <NoteBar>Password changed.</NoteBar>}

            <button className="btn btn--primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Change password"}
            </button>
          </form>
        </div>
      </div>
    </>
  );
}
