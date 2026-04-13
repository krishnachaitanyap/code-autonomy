'use client';

/**
 * Admin user management page (/admin/users).
 *
 * Lists all users that have ever logged in via SSO, with controls to:
 *   - change a user's role (admin / developer / viewer)
 *   - activate/deactivate accounts (soft-disable login)
 *
 * Access is gated three ways:
 *   1. If SSO is disabled entirely, shows an empty-state explaining how to
 *      enable it via [auth].provider = oidc in config.ini
 *   2. If the current user is not an admin, shows "Access Denied"
 *   3. The backend also enforces admin role on every /api/auth/users/*
 *      endpoint, so direct API calls cannot bypass the UI check
 *
 * The current user cannot edit their own role or deactivate themselves —
 * the controls are disabled for the current row to prevent self-lockout.
 */

import { useEffect, useState } from 'react';
import { useAuth, canManageUsers, listUsers, updateUserRole, toggleUserActive, type User } from '@/lib/auth';

/**
 * Safely render the SSO provider as a hostname.
 *
 * Different providers store different things in `sso_provider`:
 *   OIDC → the issuer URL (e.g. "https://yourorg.okta.com/oauth2/default")
 *   ADFS → the authorize URL (e.g. "https://adfs.example.com/adfs/oauth2/authorize")
 *   Mock → a plain string like "mock" or "adfs-local"
 *
 * `new URL(...)` throws on plain strings, so we fall back to displaying the
 * raw value (or "—") when it isn't parseable as a URL.
 */
function ssoProviderLabel(raw: string | null | undefined): string {
  if (!raw) return '—';
  try {
    return new URL(raw).hostname;
  } catch {
    return raw;
  }
}

const ROLE_BADGE_COLORS: Record<string, string> = {
  admin: 'bg-red-100 text-red-700',
  developer: 'bg-blue-100 text-blue-700',
  viewer: 'bg-gray-100 text-gray-600',
};

export default function UsersPage() {
  const { user: currentUser, authEnabled } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      setLoading(true);
      const data = await listUsers();
      setUsers(data.users);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      const updated = await updateUserRole(userId, newRole);
      setUsers(prev => prev.map(u => u.id === userId ? updated : u));
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleToggleActive = async (userId: string) => {
    try {
      const updated = await toggleUserActive(userId);
      setUsers(prev => prev.map(u => u.id === userId ? updated : u));
    } catch (err: any) {
      setError(err.message);
    }
  };

  if (!authEnabled) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg font-medium">Authentication not enabled</p>
        <p className="mt-2">Set <code className="bg-gray-100 px-2 py-0.5 rounded">[auth] provider = oidc</code> in config.ini to enable user management.</p>
      </div>
    );
  }

  if (currentUser && !canManageUsers(currentUser.role)) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg font-medium">Access Denied</p>
        <p className="mt-2">Admin role required to manage users.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
          <p className="text-sm text-gray-500 mt-1">{users.length} user{users.length !== 1 ? 's' : ''} registered</p>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-md text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-8 text-gray-400">Loading users...</div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Role</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Team</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">SSO Provider</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Login</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {users.map((u) => (
                <tr key={u.id} className={!u.is_active ? 'bg-gray-50 opacity-60' : ''}>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-sm font-bold">
                        {(u.display_name || u.email).charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-900">{u.display_name || '—'}</div>
                        <div className="text-xs text-gray-500">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <select
                      value={u.role}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                      disabled={u.id === currentUser?.id}
                      className="text-xs border border-gray-300 rounded px-2 py-1 bg-white disabled:opacity-50"
                    >
                      <option value="admin">Admin</option>
                      <option value="developer">Developer</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {u.team_id || '—'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {ssoProviderLabel(u.sso_provider)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-500">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {u.id !== currentUser?.id && (
                      <button
                        onClick={() => handleToggleActive(u.id)}
                        className="text-xs text-gray-500 hover:text-gray-700 underline"
                      >
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
