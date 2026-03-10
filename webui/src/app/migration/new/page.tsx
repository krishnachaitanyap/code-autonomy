'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { repos, migrations, type Repo } from '@/lib/api';

type WizardStep = 1 | 2 | 3;

export default function NewMigrationWizard() {
  const router = useRouter();
  const [step, setStep] = useState<WizardStep>(1);
  const [existingRepos, setExistingRepos] = useState<Repo[]>([]);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  const [form, setForm] = useState({
    name: '',
    migration_mode: 'migration' as 'migration' | 'improvement',
    // Source
    source_mode: 'url' as 'url' | 'path' | 'existing',
    source_repo_id: '',
    source_repo_url: '',
    source_local_path: '',
    source_branch: 'main',
    // Reference
    reference_repo_url: '',
    reference_local_path: '',
    reference_branch: 'main',
    reference_folders: [] as string[],
  });

  useEffect(() => {
    repos.list().then(setExistingRepos).catch(() => {});
  }, []);

  const handleCreate = async () => {
    setError('');
    setCreating(true);
    try {
      const sourceUrl = form.source_mode === 'existing'
        ? existingRepos.find(r => r.id === form.source_repo_id)?.url || ''
        : form.source_repo_url;
      const sourcePath = form.source_mode === 'existing'
        ? existingRepos.find(r => r.id === form.source_repo_id)?.local_path || ''
        : form.source_local_path;

      const project = await migrations.createProject({
        name: form.name,
        migration_mode: form.migration_mode,
        source_repo_url: sourceUrl,
        source_local_path: sourcePath,
        source_branch: form.source_branch,
        reference_repo_url: form.reference_repo_url,
        reference_local_path: form.reference_local_path,
        reference_branch: form.reference_branch,
        reference_folders: form.reference_folders,
      });

      // Trigger analysis immediately
      await migrations.analyzeProject(project.id);

      router.push(`/migration/${project.id}`);
    } catch (err: any) {
      setError(err.message || 'Failed to create project');
      setCreating(false);
    }
  };

  const isImprovement = form.migration_mode === 'improvement';

  const canNext = () => {
    if (step === 1) {
      if (!form.name) return false;
      if (form.source_mode === 'url' && !form.source_repo_url) return false;
      if (form.source_mode === 'path' && !form.source_local_path) return false;
      if (form.source_mode === 'existing' && !form.source_repo_id) return false;
      return true;
    }
    if (step === 2) {
      // Reference is optional in improvement mode
      return isImprovement || !!(form.reference_repo_url || form.reference_local_path);
    }
    return true;
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold text-gray-900 mb-1">New Migration Project</h1>
      <p className="text-sm text-gray-500 mb-6">
        {isImprovement
          ? 'Analyze your repository for quality, testing, performance, and structural improvements.'
          : 'Compare your source repository against a golden reference template.'}
      </p>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {[1, 2, 3].map(s => (
          <div key={s} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
              step === s ? 'bg-indigo-600 text-white' :
              step > s ? 'bg-green-100 text-green-700' :
              'bg-gray-100 text-gray-500'
            }`}>
              {step > s ? '\u2713' : s}
            </div>
            <span className={`text-sm ${step === s ? 'text-gray-900 font-medium' : 'text-gray-500'}`}>
              {s === 1 ? 'Repository' : s === 2 ? (isImprovement ? 'Reference (Optional)' : 'Reference') : 'Review'}
            </span>
            {s < 3 && <div className="w-12 h-0.5 bg-gray-200" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm mb-4">
          {error}
        </div>
      )}

      {/* Step 1: Source Repository */}
      {step === 1 && (
        <div className="space-y-4">
          {/* Mode toggle */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Mode</label>
            <div className="flex gap-2">
              <button
                onClick={() => setForm({ ...form, migration_mode: 'migration' })}
                className={`flex-1 px-3 py-2 rounded-md text-sm border transition-colors ${
                  form.migration_mode === 'migration'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="font-medium">Migration</div>
                <div className="text-[10px] mt-0.5 opacity-75">Source vs Reference comparison</div>
              </button>
              <button
                onClick={() => setForm({ ...form, migration_mode: 'improvement' })}
                className={`flex-1 px-3 py-2 rounded-md text-sm border transition-colors ${
                  form.migration_mode === 'improvement'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="font-medium">Improvement</div>
                <div className="text-[10px] mt-0.5 opacity-75">Quality, testing, performance analysis</div>
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. my-service migration to v2"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Source Repository</label>
            <div className="flex gap-2 mb-3">
              {(['url', 'path', 'existing'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => setForm({ ...form, source_mode: mode })}
                  className={`px-3 py-1.5 text-xs rounded-md ${
                    form.source_mode === mode
                      ? 'bg-indigo-100 text-indigo-700 font-medium'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {mode === 'url' ? 'Git URL' : mode === 'path' ? 'Local Path' : 'Existing Repo'}
                </button>
              ))}
            </div>

            {form.source_mode === 'url' && (
              <input
                type="text"
                value={form.source_repo_url}
                onChange={e => setForm({ ...form, source_repo_url: e.target.value })}
                placeholder="https://github.com/org/repo.git"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            )}
            {form.source_mode === 'path' && (
              <input
                type="text"
                value={form.source_local_path}
                onChange={e => setForm({ ...form, source_local_path: e.target.value })}
                placeholder="/path/to/repo"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            )}
            {form.source_mode === 'existing' && (
              <select
                value={form.source_repo_id}
                onChange={e => setForm({ ...form, source_repo_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">Select a repo...</option>
                {existingRepos.map(r => (
                  <option key={r.id} value={r.id}>{r.url || r.local_path || r.id}</option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
            <input
              type="text"
              value={form.source_branch}
              onChange={e => setForm({ ...form, source_branch: e.target.value })}
              placeholder="main"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      )}

      {/* Step 2: Reference Repository */}
      {step === 2 && (
        <div className="space-y-4">
          {isImprovement && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-xs text-blue-700">
              In improvement mode, a reference repo is optional. If provided, it will be used for
              additional comparison alongside the quality analysis.
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Reference Repository URL</label>
            <input
              type="text"
              value={form.reference_repo_url}
              onChange={e => setForm({ ...form, reference_repo_url: e.target.value })}
              placeholder="https://github.com/org/golden-template.git"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200" /></div>
            <div className="relative flex justify-center text-sm"><span className="bg-white px-2 text-gray-400">or</span></div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Reference Local Path</label>
            <input
              type="text"
              value={form.reference_local_path}
              onChange={e => setForm({ ...form, reference_local_path: e.target.value })}
              placeholder="/path/to/golden-template"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
            <input
              type="text"
              value={form.reference_branch}
              onChange={e => setForm({ ...form, reference_branch: e.target.value })}
              placeholder="main"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Reference Folders <span className="text-gray-400 font-normal">(optional, comma-separated)</span>
            </label>
            <input
              type="text"
              value={form.reference_folders.join(', ')}
              onChange={e => setForm({ ...form, reference_folders: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
              placeholder="src/main, k8s, docker"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      )}

      {/* Step 3: Review */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Review Migration Project</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Mode</dt>
                <dd className={`font-medium capitalize ${isImprovement ? 'text-emerald-700' : 'text-indigo-700'}`}>
                  {form.migration_mode}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Name</dt>
                <dd className="text-gray-900 font-medium">{form.name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Source</dt>
                <dd className="text-gray-900 truncate max-w-xs">
                  {form.source_mode === 'existing'
                    ? existingRepos.find(r => r.id === form.source_repo_id)?.url || form.source_repo_id
                    : form.source_repo_url || form.source_local_path}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Source Branch</dt>
                <dd className="text-gray-900">{form.source_branch}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Reference</dt>
                <dd className="text-gray-900 truncate max-w-xs">
                  {form.reference_repo_url || form.reference_local_path}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Reference Branch</dt>
                <dd className="text-gray-900">{form.reference_branch}</dd>
              </div>
              {form.reference_folders.length > 0 && (
                <div className="flex justify-between">
                  <dt className="text-gray-500">Folders</dt>
                  <dd className="text-gray-900">{form.reference_folders.join(', ')}</dd>
                </div>
              )}
            </dl>
          </div>
          <p className="text-xs text-gray-400">
            {isImprovement
              ? 'After creation, quality and improvement analysis will start automatically.'
              : 'After creation, stack analysis will start automatically on both repositories.'}
          </p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between mt-8">
        <button
          onClick={() => setStep((step - 1) as WizardStep)}
          disabled={step === 1}
          className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Back
        </button>
        {step < 3 ? (
          <button
            onClick={() => setStep((step + 1) as WizardStep)}
            disabled={!canNext()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            Next
          </button>
        ) : (
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create & Analyze'}
          </button>
        )}
      </div>
    </div>
  );
}
