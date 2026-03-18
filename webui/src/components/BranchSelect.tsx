'use client';

import { useEffect, useState } from 'react';
import { repos } from '@/lib/api';

interface BranchSelectProps {
  /** Repo ID to fetch branches for. When empty, dropdown shows "main" only. */
  repoId: string;
  /** Currently selected branch value. */
  value: string;
  /** Called when user picks a branch. */
  onChange: (branch: string) => void;
  /** Extra CSS classes for the <select> element. */
  className?: string;
  /** Disable the control. */
  disabled?: boolean;
  /** Label size variant: "sm" for compact forms. */
  size?: 'sm' | 'md';
}

/**
 * Reusable branch dropdown that:
 * 1. Fetches branches + current_branch from the API when repoId changes
 * 2. Auto-selects the workspace's current branch (if available)
 * 3. Highlights the current workspace branch with a visual indicator
 */
export default function BranchSelect({
  repoId,
  value,
  onChange,
  className = '',
  disabled = false,
  size = 'md',
}: BranchSelectProps) {
  const [branchList, setBranchList] = useState<string[]>([]);
  const [currentBranch, setCurrentBranch] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!repoId) {
      setBranchList([]);
      setCurrentBranch('');
      onChange('main');
      return;
    }

    setBranchList([]);
    setCurrentBranch('');
    setLoading(true);

    repos
      .branches(repoId)
      .then((r) => {
        const list = r.branches || [];
        const active = r.current_branch || '';
        setBranchList(list);
        setCurrentBranch(active);

        // Auto-select: prefer workspace's current branch, then 'main', then first
        if (active && list.includes(active)) {
          onChange(active);
        } else if (list.includes('main')) {
          onChange('main');
        } else if (list.length > 0) {
          onChange(list[0]);
        } else {
          onChange('main');
        }
      })
      .catch(() => {
        setBranchList([]);
        setCurrentBranch('');
        onChange('main');
      })
      .finally(() => setLoading(false));
  }, [repoId]); // eslint-disable-line react-hooks/exhaustive-deps

  const baseClass =
    size === 'sm'
      ? 'px-3 py-2 border border-gray-300 rounded text-sm'
      : 'w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500';

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${baseClass} ${className}`}
      disabled={disabled || loading || branchList.length === 0}
    >
      {loading ? (
        <option>Loading branches...</option>
      ) : branchList.length === 0 ? (
        <option value="main">main</option>
      ) : (
        branchList.map((b) => (
          <option key={b} value={b}>
            {b === currentBranch ? `${b}  \u2190 workspace` : b}
          </option>
        ))
      )}
    </select>
  );
}
