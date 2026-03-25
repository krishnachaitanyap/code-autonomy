'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { repos, type Repo } from '@/lib/api';
import DependencyVisualizer from '@/components/DependencyVisualizer';

function getBranchType(name: string): { label: string; color: string } {
  const n = name.toLowerCase();
  if (n === 'main' || n === 'master' || n === 'develop') {
    return { label: 'default', color: 'bg-purple-100 text-purple-800' };
  }
  if (n.startsWith('feature/') || n.startsWith('feature-')) {
    return { label: 'feature', color: 'bg-blue-100 text-blue-800' };
  }
  if (n.startsWith('bugfix/') || n.startsWith('bugfix-') || n.startsWith('hotfix/') || n.startsWith('hotfix-')) {
    return { label: 'bugfix', color: 'bg-red-100 text-red-800' };
  }
  if (n.startsWith('release/') || n.startsWith('release-')) {
    return { label: 'release', color: 'bg-green-100 text-green-800' };
  }
  return { label: 'other', color: 'bg-gray-100 text-gray-700' };
}

function isDefaultBranch(name: string): boolean {
  const n = name.toLowerCase();
  return n === 'main' || n === 'master' || n === 'develop';
}

export default function RepoDetailPage() {
  const params = useParams();
  const router = useRouter();
  const repoId = params.id as string;

  const [repo, setRepo] = useState<Repo | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [branchSearch, setBranchSearch] = useState('');
  const [skills, setSkills] = useState('');
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [claudeMd, setClaudeMd] = useState('');
  const [claudeMdLoading, setClaudeMdLoading] = useState(true);
  const [claudeMdSaving, setClaudeMdSaving] = useState(false);
  const [claudeMdSaved, setClaudeMdSaved] = useState(false);
  const [claudeMdGenerating, setClaudeMdGenerating] = useState(false);
  const [skillsPreview, setSkillsPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const [repoData, branchData, skillsData, claudeMdData] = await Promise.all([
          repos.get(repoId),
          repos.branches(repoId).catch(() => ({ branches: [] })),
          repos.getSkills(repoId).catch(() => ({ content: '' })),
          repos.getClaudeMd(repoId).catch(() => ({ content: '' })),
        ]);
        setRepo(repoData);
        setBranches(branchData.branches);
        setSkills(skillsData.content);
        setClaudeMd(claudeMdData.content);
      } catch (err: any) {
        setError(err.message || 'Failed to load repository');
      } finally {
        setLoading(false);
        setSkillsLoading(false);
        setClaudeMdLoading(false);
      }
    }
    load();
  }, [repoId]);

  async function handleDelete() {
    if (!confirm('Are you sure you want to delete this repository? This will remove all related sessions, knowledge, and data.')) {
      return;
    }
    try {
      await repos.delete(repoId);
      router.push('/repos');
    } catch (err: any) {
      alert(err.message || 'Failed to delete repo');
    }
  }

  async function handleSaveSkills() {
    setSaving(true);
    setSaved(false);
    try {
      await repos.updateSkills(repoId, skills);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: any) {
      alert(err.message || 'Failed to save SKILLS.md');
    } finally {
      setSaving(false);
    }
  }

  async function handleGenerateSkills() {
    setGenerating(true);
    try {
      const result = await repos.generateSkills(repoId);
      setSkills(result.content);
    } catch (err: any) {
      alert(err.message || 'Failed to generate SKILLS.md');
    } finally {
      setGenerating(false);
    }
  }

  async function handleSaveClaudeMd() {
    setClaudeMdSaving(true);
    setClaudeMdSaved(false);
    try {
      await repos.updateClaudeMd(repoId, claudeMd);
      setClaudeMdSaved(true);
      setTimeout(() => setClaudeMdSaved(false), 3000);
    } catch (err: any) {
      alert(err.message || 'Failed to save CLAUDE.md');
    } finally {
      setClaudeMdSaving(false);
    }
  }

  async function handleGenerateClaudeMd() {
    setClaudeMdGenerating(true);
    try {
      const result = await repos.generateClaudeMd(repoId);
      setClaudeMd(result.content);
    } catch (err: any) {
      alert(err.message || 'Failed to generate CLAUDE.md');
    } finally {
      setClaudeMdGenerating(false);
    }
  }

  const platformColor: Record<string, string> = {
    github: 'bg-gray-800 text-white',
    bitbucket: 'bg-blue-600 text-white',
    local: 'bg-green-600 text-white',
  };

  // Sort branches: default branches pinned to top, then alphabetical
  const sortedBranches = [...branches].sort((a, b) => {
    const aDefault = isDefaultBranch(a);
    const bDefault = isDefaultBranch(b);
    if (aDefault && !bDefault) return -1;
    if (!aDefault && bDefault) return 1;
    return a.localeCompare(b);
  });

  const filteredBranches = branchSearch
    ? sortedBranches.filter((b) => b.toLowerCase().includes(branchSearch.toLowerCase()))
    : sortedBranches;

  if (loading) {
    return <p className="text-gray-500">Loading repository...</p>;
  }

  if (error || !repo) {
    return <p className="text-red-600">{error || 'Repository not found'}</p>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold text-gray-900 truncate">
            {repo.nickname || repo.url || repo.local_path}
          </h1>
          <div className="flex items-center gap-3 mt-2">
            <span
              className={`px-2 py-1 rounded text-xs font-medium ${
                platformColor[repo.platform] || 'bg-gray-200 text-gray-700'
              }`}
            >
              {repo.platform}
            </span>
            <span className="text-sm text-gray-500">ID: {repo.id}</span>
          </div>
        </div>
        <button
          onClick={handleDelete}
          className="px-4 py-2 bg-red-600 text-white rounded-md text-sm font-medium hover:bg-red-700 transition-colors"
        >
          Delete Repo
        </button>
      </div>

      {/* Info Grid */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Info</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Local Path</dt>
            <dd className="text-gray-900 font-mono mt-1 break-all">{repo.local_path || '(none)'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">URL</dt>
            <dd className="text-gray-900 font-mono mt-1 break-all">{repo.url || '(none)'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Created</dt>
            <dd className="text-gray-900 mt-1">{new Date(repo.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Updated</dt>
            <dd className="text-gray-900 mt-1">{new Date(repo.updated_at).toLocaleString()}</dd>
          </div>
        </dl>
      </div>

      {/* Branches */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Branches{branches.length > 0 && ` (${branches.length})`}
        </h2>
        {branches.length === 0 ? (
          <p className="text-sm text-gray-500">No branches found.</p>
        ) : (
          <>
            <input
              type="text"
              value={branchSearch}
              onChange={(e) => setBranchSearch(e.target.value)}
              placeholder="Search branches..."
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mb-3 focus:ring-indigo-500 focus:border-indigo-500"
            />
            {filteredBranches.length === 0 ? (
              <p className="text-sm text-gray-500">No branches match "{branchSearch}"</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {filteredBranches.map((branch) => {
                  const { label, color } = getBranchType(branch);
                  return (
                    <span
                      key={branch}
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm font-mono ${color}`}
                    >
                      {isDefaultBranch(branch) && (
                        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                        </svg>
                      )}
                      {branch}
                      <span className="text-[10px] opacity-70 font-sans">{label}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* Dependency Visualizer */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Dependencies</h2>
        <p className="text-sm text-gray-500 mb-4">
          Downstream services, data stores, messaging, and API endpoints detected via static analysis.
        </p>
        <DependencyVisualizer repoId={repoId} repoName={repo.nickname || repo.url || repo.local_path || repoId} />
      </div>

      {/* SKILLS.md Editor */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">SKILLS.md</h2>
            <p className="text-sm text-gray-500 mt-1">
              Per-repo knowledge file injected into agent prompts. Use it to teach the agent about this repo's conventions, patterns, and domain.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {saved && (
              <span className="text-sm text-green-600 font-medium">Saved</span>
            )}
            {skills && (
              <button
                onClick={() => {
                  const blob = new Blob([skills], { type: 'text/markdown' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'SKILLS.md';
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-50 transition-colors"
              >
                Download
              </button>
            )}
            <button
              onClick={handleGenerateSkills}
              disabled={generating || skillsLoading}
              className="px-4 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {generating ? 'Generating...' : skills ? 'Regenerate' : 'Generate'}
            </button>
            <button
              onClick={handleSaveSkills}
              disabled={saving || skillsLoading}
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
        {/* Edit / Preview toggle */}
        <div className="flex items-center gap-1 mb-2 border-b border-gray-200">
          <button
            onClick={() => setSkillsPreview(false)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors ${
              !skillsPreview ? 'bg-white border border-b-white border-gray-200 text-gray-900 -mb-px' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Edit
          </button>
          <button
            onClick={() => setSkillsPreview(true)}
            disabled={!skills}
            className={`px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors disabled:opacity-40 ${
              skillsPreview ? 'bg-white border border-b-white border-gray-200 text-gray-900 -mb-px' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Preview
          </button>
        </div>
        {skillsPreview ? (
          <div
            className="w-full border border-gray-300 rounded-md px-4 py-3 text-sm prose prose-sm max-w-none overflow-auto bg-gray-50/50"
            style={{ minHeight: '16rem', maxHeight: '40rem' }}
            dangerouslySetInnerHTML={{
              __html: skills
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/^### (.+)$/gm, '<h3 class="text-sm font-semibold text-gray-800 mt-4 mb-1">$1</h3>')
                .replace(/^## (.+)$/gm, '<h2 class="text-base font-bold text-gray-900 mt-5 mb-2 pb-1 border-b border-gray-200">$1</h2>')
                .replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold text-gray-900 mt-4 mb-3">$1</h1>')
                .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-gray-800 text-gray-100 rounded-md px-3 py-2 text-xs overflow-x-auto my-2"><code>$2</code></pre>')
                .replace(/`([^`]+)`/g, '<code class="bg-gray-100 text-pink-700 px-1 py-0.5 rounded text-xs">$1</code>')
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/\*([^*]+)\*/g, '<em>$1</em>')
                .replace(/^\|(.+)\|$/gm, (match) => {
                  const cells = match.split('|').filter(c => c.trim()).map(c => `<td class="px-2 py-1 border border-gray-200 text-xs">${c.trim()}</td>`);
                  return `<tr>${cells.join('')}</tr>`;
                })
                .replace(/(<tr>.*<\/tr>\n?)+/g, '<table class="w-full border-collapse my-2">$&</table>')
                .replace(/^- (.+)$/gm, '<li class="ml-4 text-sm">$1</li>')
                .replace(/(<li.*<\/li>\n?)+/g, '<ul class="list-disc my-1">$&</ul>')
                .replace(/\n{2,}/g, '<br/><br/>')
                .replace(/\n/g, '<br/>')
            }}
          />
        ) : (
          <textarea
            value={skills}
            onChange={(e) => setSkills(e.target.value)}
            rows={16}
            placeholder="# SKILLS.md&#10;&#10;Describe repo conventions, domain knowledge, testing patterns, etc."
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500 resize-y"
            disabled={skillsLoading}
          />
        )}
      </div>

      {/* CLAUDE.md Editor */}
      <div className="bg-white rounded-lg border border-teal-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">CLAUDE.md</h2>
            <p className="text-sm text-gray-500 mt-1">
              Prescriptive rules for Claude Code — auto-generated from stack analysis.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {claudeMdSaved && (
              <span className="text-sm text-green-600 font-medium">Saved</span>
            )}
            <button
              onClick={handleGenerateClaudeMd}
              disabled={claudeMdGenerating || claudeMdLoading}
              className="px-4 py-2 bg-teal-600 text-white rounded-md text-sm font-medium hover:bg-teal-700 disabled:opacity-50 transition-colors"
            >
              {claudeMdGenerating ? 'Generating...' : claudeMd ? 'Regenerate' : 'Generate'}
            </button>
            <button
              onClick={handleSaveClaudeMd}
              disabled={claudeMdSaving || claudeMdLoading}
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {claudeMdSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
        <textarea
          value={claudeMd}
          onChange={(e) => setClaudeMd(e.target.value)}
          rows={16}
          placeholder="# CLAUDE.md&#10;&#10;Prescriptive rules — build commands, API patterns, data-layer rules, etc."
          className="w-full border border-teal-300 rounded-md px-3 py-2 text-sm font-mono focus:ring-teal-500 focus:border-teal-500 resize-y"
          disabled={claudeMdLoading}
        />
      </div>
    </div>
  );
}
