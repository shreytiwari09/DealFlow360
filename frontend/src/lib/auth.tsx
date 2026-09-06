/**
 * Authentication context.
 *
 * `permissions` here drives which controls are shown. That is UX only: every
 * endpoint re-checks server-side, so hiding a button is a courtesy, never a
 * control (SECURITY_SPEC.md Section 1).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, logout as apiLogout, setAccessToken } from "./api";
import type { CurrentUser, TokenResponse } from "./api";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName: string) => Promise<void>;
  acceptInvitation: (token: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  // On first load, try to resume a session from the HttpOnly refresh cookie.
  // There is nothing to check for existence first anymore (no stored token
  // to read) — `api.get` triggers its own refresh-and-replay on a 401, which
  // either succeeds (the cookie was valid) or fails generically (there was
  // none, or it expired) exactly like any other unauthenticated request. A
  // brand-new tab or a fresh page load looks identical to this code now,
  // which is the whole point: the browser's cookie jar is shared, so there
  // is no separate "does THIS tab know about the session" question left to
  // answer the way sessionStorage/localStorage used to require.
  useEffect(() => {
    let cancelled = false;
    async function resume() {
      try {
        const me = await api.get<CurrentUser>("/auth/me");
        if (!cancelled) setUser(me);
      } catch {
        setAccessToken(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void resume();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const tokens = await api.post<TokenResponse>("/auth/login", { email, password });
    setAccessToken(tokens.access_token);
    setUser(await api.get<CurrentUser>("/auth/me"));
  }, []);

  /**
   * PRD A1: "Internal users can sign up and log in." Signup issues a token
   * pair immediately (see `services/auth.py`'s `signup()`), so this is the
   * same shape as `signIn` — one call, then the session is live.
   */
  const signUp = useCallback(async (email: string, password: string, fullName: string) => {
    const tokens = await api.post<TokenResponse>("/auth/signup", {
      email,
      password,
      full_name: fullName,
    });
    setAccessToken(tokens.access_token);
    setUser(await api.get<CurrentUser>("/auth/me"));
  }, []);

  /**
   * The activation half of an Admin-issued invite (`services/invitation.py`).
   * Same shape as `signUp`: proving ownership of the link IS the credential,
   * so setting a password logs the invitee straight in rather than sending
   * them to /login a second time.
   */
  const acceptInvitation = useCallback(async (token: string, password: string) => {
    const tokens = await api.post<TokenResponse>(`/auth/invitations/${token}/accept`, {
      password,
    });
    setAccessToken(tokens.access_token);
    setUser(await api.get<CurrentUser>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signIn,
      signUp,
      acceptInvitation,
      signOut,
      can: (permission: string) => user?.permissions.includes(permission) ?? false,
    }),
    [user, loading, signIn, signUp, acceptInvitation, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
