'use client';

/**
 * Frontend auth client.
 *
 * Wraps the /api/auth/* endpoints exposed by src/api/routes/auth.py and
 * provides a React Context (AuthContext) so any component can read the
 * current user via useAuth(). The session lives in an httpOnly cookie set
 * by the backend during the OIDC callback, so the frontend never touches
 * the JWT directly — credentials: 'include' is required on every request.
 *
 * Role helpers (canRunAgent, canManageUsers, canExecutePipeline) centralize
 * role-based UI gating so individual pages don't need to know the role
 * hierarchy.
 */

import { createContext, useContext } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string;
  sso_provider: string;
  role: 'admin' | 'developer' | 'viewer';
  team_id: string | null;
  cost_center: string | null;
  avatar_url: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string | null;
}

export interface AuthState {
  user: User | null;
  authEnabled: boolean;
  loading: boolean;
}

// ---------------------------------------------------------------------------
// localStorage token + user helpers (ADFS browser-initiated flow)
// ---------------------------------------------------------------------------
//
// The ADFS flow stores the JWT and user JSON in localStorage so the frontend
// can attach `Authorization: Bearer <token>` to every API call. SSR-safe:
// these helpers no-op if `window` is undefined (Next.js server render).

const TOKEN_KEY = 'jwt_token';
const USER_KEY = 'user';
const SSO_STATE_KEY = 'sso_state';

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): User | null {
  if (typeof window === 'undefined') return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function setStoredAuth(token: string, user: User | unknown): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, typeof user === 'string' ? user : JSON.stringify(user));
}

export function clearStoredAuth(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.sessionStorage.removeItem(SSO_STATE_KEY);
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

/**
 * Drop-in replacement for `fetch` that injects the localStorage JWT as a
 * Bearer token on every request. Use this from any module that talks to
 * the backend so we don't scatter token-injection logic across the app.
 *
 * Auto-clears stored auth and triggers a re-login on 401, so an expired
 * JWT bounces the user through SSO again instead of leaving them in a
 * broken state.
 */
export async function authedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(init.headers || {});
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const res = await fetch(input, { ...init, headers, credentials: 'include' });

  if (res.status === 401 && typeof window !== 'undefined') {
    clearStoredAuth();
    // Avoid infinite loops if /auth/sso/* themselves return 401
    const url = typeof input === 'string' ? input : input.toString();
    if (!url.includes('/auth/sso/')) {
      // Defer re-login one tick so the caller can read the response if needed
      setTimeout(() => { void initiateSSOLogin(); }, 0);
    }
  }

  return res;
}

/**
 * Build the ADFS authorize URL on the client and redirect.
 *
 * Steps (Section 4.2 of the SSO spec):
 *   1. Generate a CSRF state value, store in sessionStorage
 *   2. GET /api/auth/sso/config to fetch the public IdP config
 *   3. Construct the ADFS authorize URL with response_mode=query, scope=openid,
 *      and the ADFS-specific `resource` parameter
 *   4. window.location.replace() to navigate
 *   5. On any failure, fall back to the backend's /auth/sso/auth?state= endpoint
 */
export async function initiateSSOLogin(): Promise<void> {
  if (typeof window === 'undefined') return;

  // 1. Generate and persist CSRF state
  let state: string;
  try {
    state = window.crypto.randomUUID();
  } catch {
    // Older browser fallback
    state = Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  window.sessionStorage.setItem(SSO_STATE_KEY, state);

  try {
    // 2. Fetch the public SSO config
    const cfgRes = await fetch(`${API_BASE}/auth/sso/config`);
    if (!cfgRes.ok) throw new Error(`config fetch failed: ${cfgRes.status}`);
    const cfg = await cfgRes.json();

    if (!cfg.enabled || !cfg.authorization_url || !cfg.client_id) {
      throw new Error('SSO config incomplete');
    }

    // 3. Construct the ADFS authorize URL
    const params = new URLSearchParams({
      client_id: cfg.client_id,
      response_type: 'code',
      redirect_uri: cfg.redirect_uri || '',
      response_mode: 'query',
      resource: cfg.resource || '',
      scope: 'openid',
      state,
    });
    const url = `${cfg.authorization_url}?${params.toString()}`;

    // 4. Navigate
    window.location.replace(url);
  } catch (err) {
    // 5. Backend fallback — let the server build the URL
    console.warn('initiateSSOLogin: client URL build failed, using backend fallback', err);
    window.location.replace(`${API_BASE}/auth/sso/auth?state=${encodeURIComponent(state)}`);
  }
}

export async function getCurrentUser(): Promise<{ user: User | null; auth_enabled: boolean }> {
  // Prefer the locally cached user (set by AuthProvider after callback parse)
  // so we don't make a network round-trip on every page load.
  const cached = getStoredUser();
  if (cached) {
    return { user: cached, auth_enabled: true };
  }

  const res = await authedFetch(`${API_BASE}/auth/me`);
  if (res.status === 401) {
    return { user: null, auth_enabled: true };
  }
  if (!res.ok) {
    return { user: null, auth_enabled: false };
  }
  return res.json();
}

export async function logout(): Promise<void> {
  const user = getStoredUser();
  // Best-effort: invalidate the server-side ADFS token cache. The internal
  // JWT itself is stateless and cannot be revoked, so we also clear local
  // storage so the next API call triggers a re-login.
  try {
    if (user?.id) {
      await authedFetch(`${API_BASE}/auth/sso/logout?user_id=${encodeURIComponent(user.id)}`, {
        method: 'POST',
      });
    } else {
      await authedFetch(`${API_BASE}/auth/logout`, { method: 'POST' });
    }
  } catch {
    // ignore — clearing localStorage below is the important part
  }
  clearStoredAuth();
  if (typeof window !== 'undefined') {
    window.location.href = '/';
  }
}

export async function listUsers(): Promise<{ users: User[]; total: number }> {
  const res = await authedFetch(`${API_BASE}/auth/users`);
  if (!res.ok) throw new Error('Failed to fetch users');
  return res.json();
}

export async function updateUserRole(userId: string, role: string): Promise<User> {
  const res = await authedFetch(`${API_BASE}/auth/users/${userId}/role?role=${role}`, {
    method: 'PUT',
  });
  if (!res.ok) throw new Error('Failed to update role');
  return res.json();
}

export async function toggleUserActive(userId: string): Promise<User> {
  const res = await authedFetch(`${API_BASE}/auth/users/${userId}/toggle-active`, {
    method: 'PUT',
  });
  if (!res.ok) throw new Error('Failed to toggle user status');
  return res.json();
}

/**
 * Build a WebSocket URL with the JWT appended as ?token=... — browsers
 * cannot send custom headers on WebSocket upgrades, so the query param is
 * the standard workaround. Returns the input URL unchanged when no token
 * is stored (open-access mode).
 */
export function withWsToken(wsUrl: string): string {
  const token = getStoredToken();
  if (!token) return wsUrl;
  const sep = wsUrl.includes('?') ? '&' : '?';
  return `${wsUrl}${sep}token=${encodeURIComponent(token)}`;
}

// ---------------------------------------------------------------------------
// React Context
// ---------------------------------------------------------------------------

export const AuthContext = createContext<AuthState>({
  user: null,
  authEnabled: false,
  loading: true,
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

// ---------------------------------------------------------------------------
// Role helpers
// ---------------------------------------------------------------------------

export function canRunAgent(role?: string): boolean {
  return role === 'admin' || role === 'developer';
}

export function canManageUsers(role?: string): boolean {
  return role === 'admin';
}

export function canExecutePipeline(role?: string): boolean {
  return role === 'admin' || role === 'developer';
}
