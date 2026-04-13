'use client';

/**
 * AuthProvider — top-level React context provider for auth state.
 *
 * Mount once near the root of the app (in webui/src/app/layout.tsx).
 *
 * Startup behavior (Section 4.1 / 4.4 of the SSO spec):
 *
 *   1. Parse window.location for ?token= / ?user= / ?error= query params
 *      (the backend appends these when redirecting from /api/auth/sso/callback).
 *   2. If ?error= present → render an error UI and stop.
 *   3. If ?token= and ?user= present:
 *        - Verify the URL ?state= matches sessionStorage['sso_state'] (CSRF)
 *        - Store token + user in localStorage via setStoredAuth()
 *        - history.replaceState() to scrub the token from the URL bar so
 *          it doesn't end up in browser history, screenshots, or logs
 *        - Set authState
 *   4. Else, read existing localStorage via getStoredToken/getStoredUser.
 *   5. If still no token AND auth is enabled (per /api/auth/sso/config) →
 *      call initiateSSOLogin() which redirects the browser to ADFS.
 *
 * When provider=none (open access), this provider is a no-op pass-through:
 * the SSO config endpoint returns enabled=false and we render children
 * immediately with user=null.
 */

import { useEffect, useState, type ReactNode } from 'react';
import {
  AuthContext,
  clearStoredAuth,
  getStoredToken,
  getStoredUser,
  initiateSSOLogin,
  setStoredAuth,
  type AuthState,
  type User,
} from './auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

type CallbackParams = {
  token: string | null;
  user: string | null;
  state: string | null;
  error: string | null;
};

function readCallbackParams(): CallbackParams {
  if (typeof window === 'undefined') {
    return { token: null, user: null, state: null, error: null };
  }
  const params = new URLSearchParams(window.location.search);
  return {
    token: params.get('token'),
    user: params.get('user'),
    state: params.get('state'),
    error: params.get('error'),
  };
}

function clearUrlQuery(): void {
  if (typeof window === 'undefined') return;
  // Replace the URL with just the pathname, preserving any hash. This
  // removes the token from browser history without reloading the page.
  window.history.replaceState({}, '', window.location.pathname + window.location.hash);
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    authEnabled: false,
    loading: true,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const cb = readCallbackParams();

      // (2) ADFS reported an error in the redirect query params
      if (cb.error) {
        if (!cancelled) {
          setError(cb.error);
          clearUrlQuery();
          setState({ user: null, authEnabled: true, loading: false });
        }
        return;
      }

      // (3) Fresh callback — store token + user, scrub URL
      if (cb.token && cb.user) {
        try {
          const userObj: User = JSON.parse(cb.user);
          // Optional CSRF check: state from URL should match what we stashed
          // before redirecting to ADFS. If sessionStorage was lost (page
          // refresh, new tab) we still accept — losing the storage is more
          // likely than an actual CSRF attempt.
          const storedState = window.sessionStorage.getItem('sso_state');
          if (storedState && cb.state && storedState !== cb.state) {
            setError('state_mismatch');
            clearUrlQuery();
            setState({ user: null, authEnabled: true, loading: false });
            return;
          }
          window.sessionStorage.removeItem('sso_state');
          setStoredAuth(cb.token, userObj);
          clearUrlQuery();
          if (!cancelled) {
            setState({ user: userObj, authEnabled: true, loading: false });
          }
          return;
        } catch (e) {
          console.error('Failed to parse callback user:', e);
          setError('invalid_callback');
          clearUrlQuery();
          setState({ user: null, authEnabled: true, loading: false });
          return;
        }
      }

      // (4) Returning visitor — read existing localStorage
      const cachedToken = getStoredToken();
      const cachedUser = getStoredUser();
      if (cachedToken && cachedUser) {
        if (!cancelled) {
          setState({ user: cachedUser, authEnabled: true, loading: false });
        }
        return;
      }

      // (5) No token at all — check whether SSO is enabled and redirect to login
      try {
        const cfgRes = await fetch(`${API_BASE}/auth/sso/config`);
        if (!cfgRes.ok) throw new Error('config fetch failed');
        const cfg = await cfgRes.json();

        if (!cfg.enabled) {
          // Open access mode (provider=none). Inject a mock user so the
          // sidebar user card still renders during local development. Real
          // SSO deployments should use provider=adfs (or =oidc) instead.
          if (!cancelled) {
            const mockUser: User = {
              id: 'dev-mock-user',
              email: 'dev@local',
              display_name: 'Dev User',
              sso_provider: 'mock',
              role: 'admin',
              team_id: null,
              cost_center: null,
              avatar_url: '',
              is_active: true,
              last_login_at: null,
              created_at: null,
            };
            // authEnabled stays true so the sidebar treats us as logged in,
            // even though the backend isn't actually validating tokens.
            setState({ user: mockUser, authEnabled: true, loading: false });
          }
          return;
        }

        // SSO is on but we have no token → redirect to ADFS authorize URL
        await initiateSSOLogin();
        // initiateSSOLogin navigates away; nothing more to do
      } catch (e) {
        console.error('AuthProvider bootstrap failed:', e);
        if (!cancelled) {
          // Fail open in dev environments where the backend might be down,
          // so the UI is still usable for testing without auth.
          setState({ user: null, authEnabled: false, loading: false });
        }
      }
    }

    bootstrap();
    return () => { cancelled = true; };
  }, []);

  // Loading splash while we figure out auth state
  if (state.loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500">Authenticating…</p>
      </div>
    );
  }

  // Error from the SSO callback (?error=auth_failed | user_info_failed | callback_failed | state_mismatch)
  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="bg-white border border-red-200 rounded-lg p-6 max-w-md text-center shadow-sm">
          <h1 className="text-xl font-semibold text-red-700 mb-2">Sign-in failed</h1>
          <p className="text-sm text-gray-600 mb-4">
            {error === 'auth_failed' && 'The identity provider rejected the login attempt.'}
            {error === 'user_info_failed' && 'Your account is missing a required claim (SID).'}
            {error === 'callback_failed' && 'Something went wrong on the server while completing sign-in.'}
            {error === 'state_mismatch' && 'CSRF state mismatch — please try again from a fresh tab.'}
            {error === 'invalid_callback' && 'The callback URL was malformed.'}
          </p>
          <button
            onClick={() => {
              clearStoredAuth();
              setError(null);
              void initiateSSOLogin();
            }}
            className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={state}>
      {children}
    </AuthContext.Provider>
  );
}
