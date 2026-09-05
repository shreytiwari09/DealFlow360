/**
 * Authentication context.
 *
 * `permissions` here drives which controls are shown. That is UX only: every
 * endpoint re-checks server-side, so hiding a button is a courtesy, never a
 * control (SECURITY_SPEC.md Section 1).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, getRefreshToken, setTokens } from "./api";
import type { CurrentUser, TokenResponse } from "./api";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  // On first load, try to resume a session from the stored refresh token.
  useEffect(() => {
    let cancelled = false;
    async function resume() {
      if (!getRefreshToken()) {
        setLoading(false);
        return;
      }
      try {
        // api.get triggers the refresh-and-replay path when the in-memory
        // access token is absent, so this both restores the session and
        // rotates the refresh token.
        const me = await api.get<CurrentUser>("/auth/me");
        if (!cancelled) setUser(me);
      } catch {
        setTokens(null, null);
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
    setTokens(tokens.access_token, tokens.refresh_token);
    setUser(await api.get<CurrentUser>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    const refresh = getRefreshToken();
    try {
      if (refresh) await api.post("/auth/logout", { refresh_token: refresh });
    } catch {
      /* logging out must succeed locally even if the server call does not */
    }
    setTokens(null, null);
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      can: (permission: string) => user?.permissions.includes(permission) ?? false,
    }),
    [user, loading, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
