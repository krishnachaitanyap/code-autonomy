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
// API functions
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export async function getCurrentUser(): Promise<{ user: User | null; auth_enabled: boolean }> {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' });
  if (res.status === 401) {
    return { user: null, auth_enabled: true };
  }
  if (!res.ok) {
    return { user: null, auth_enabled: false };
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' });
}

export async function listUsers(): Promise<{ users: User[]; total: number }> {
  const res = await fetch(`${API_BASE}/auth/users`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to fetch users');
  return res.json();
}

export async function updateUserRole(userId: string, role: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/users/${userId}/role?role=${role}`, {
    method: 'PUT',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to update role');
  return res.json();
}

export async function toggleUserActive(userId: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/users/${userId}/toggle-active`, {
    method: 'PUT',
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to toggle user status');
  return res.json();
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
