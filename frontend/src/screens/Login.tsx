/** Screen 1 — Login. FRONTEND.md Section 5. */

import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { NoteBar } from "../components/ui";

export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      const from = (location.state as { from?: Location } | null)?.from;
      navigate(from?.pathname ?? "/dashboard", { replace: true });
    } catch (err) {
      // Whatever went wrong, the server told us the same generic thing.
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">DealFlow360</div>
        <p className="login__tagline">Self-governing sales operations</p>

        <form onSubmit={submit} className="stack">
          <label className="field">
            <span className="field__label">Email</span>
            <input
              className="input"
              type="email"
              value={email}
              autoComplete="username"
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
              autoComplete="current-password"
              required
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {error && <div className="field__error">{error}</div>}

          <button className="btn btn--primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Log In"}
          </button>
        </form>

        <div style={{ marginTop: "var(--space-4)" }}>
          <NoteBar>
            Internal users land on the Sales Dashboard; a customer lands in the separate
            portal. There is no public sign-up — accounts are created by an Admin.
          </NoteBar>
        </div>
      </div>
    </div>
  );
}
