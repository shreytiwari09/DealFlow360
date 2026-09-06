/**
 * Registration — PRD A1 ("Internal users can sign up and log in"),
 * Locked Business Rules #5.
 *
 * Always creates a Sales Rep account. There is no role picker here on
 * purpose — the backend ignores one even if a crafted request sent it
 * (SECURITY_SPEC.md Section 8, mass-assignment), so offering one in the UI
 * would just be a control that lies about what it does.
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { NoteBar } from "../components/ui";

// A real format check on the client too — not the source of truth (the
// backend's EmailStr/email-validator is), but it catches an obviously wrong
// address before a round trip, matching the native <input type="email">
// validation the same field also gets.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Register() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const trimmedEmail = email.trim();
    if (!EMAIL_PATTERN.test(trimmedEmail)) {
      setError("Enter a valid email address, e.g. name@company.com.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      await signUp(trimmedEmail, password, fullName.trim());
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Registration failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">DealFlow360</div>
        <p className="login__tagline">Create your Sales Rep account</p>

        <form onSubmit={submit} className="stack">
          <label className="field">
            <span className="field__label">Full name</span>
            <input
              className="input"
              value={fullName}
              autoComplete="name"
              required
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Email</span>
            <input
              className="input"
              type="email"
              value={email}
              autoComplete="username"
              placeholder="name@company.com"
              required
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
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

          {error && <div className="field__error">{error}</div>}

          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Creating account…" : "Create account"}
          </button>
        </form>

        <div style={{ marginTop: "var(--space-4)" }}>
          <NoteBar>
            New accounts here are always Sales Reps — that's the only self-service role. A Sales
            Manager, Finance/Ops or Admin account, and every customer portal login, is created
            for you by an Admin, who sends you a one-time activation link.
          </NoteBar>
        </div>

        <p className="muted" style={{ textAlign: "center", marginTop: "var(--space-4)" }}>
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
