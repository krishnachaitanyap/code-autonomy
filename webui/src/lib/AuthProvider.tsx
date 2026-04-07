'use client';

/**
 * AuthProvider — top-level React context provider for auth state.
 *
 * Mount once near the root of the app (in webui/src/app/layout.tsx). On mount
 * it calls /api/auth/me to determine:
 *   - whether SSO is enabled on the backend (auth_enabled)
 *   - whether the current browser session is authenticated (user)
 *
 * If SSO is enabled but the user is not authenticated, this provider performs
 * a hard redirect to /api/auth/login, which the backend handles by 302-ing
 * to the IdP authorize endpoint. After successful login the IdP redirects
 * back to /api/auth/callback, which sets the cookie and lands the user back
 * on the UI root.
 *
 * If SSO is disabled (provider=none), this provider is a no-op pass-through
 * — the app runs in open-access mode and useAuth() returns user=null.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { AuthContext, getCurrentUser, type AuthState, type User } from './auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    authEnabled: false,
    loading: true,
  });

  useEffect(() => {
    getCurrentUser()
      .then(({ user, auth_enabled }) => {
        setState({ user, authEnabled: auth_enabled, loading: false });
      })
      .catch(() => {
        setState({ user: null, authEnabled: false, loading: false });
      });
  }, []);

  // If auth is enabled and user is not logged in, redirect to login
  if (!state.loading && state.authEnabled && !state.user) {
    // Check if we're on a page that doesn't need auth
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/api/auth')) {
      window.location.href = `${API_BASE}/auth/login`;
      return (
        <div className="flex items-center justify-center min-h-screen">
          <p className="text-gray-500">Redirecting to login...</p>
        </div>
      );
    }
  }

  return (
    <AuthContext.Provider value={state}>
      {children}
    </AuthContext.Provider>
  );
}
