'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { migrations, type MigrationProject, type MigrationRecipe, type MigrationRun } from '@/lib/api';
import MigrationStatusBadge from '@/components/migration/MigrationStatusBadge';
import GapAnalysisPanel from '@/components/migration/GapAnalysisPanel';
import RecipeGrid from '@/components/migration/RecipeGrid';
import CapacityForm from '@/components/migration/CapacityForm';
import RoadmapTimeline from '@/components/migration/RoadmapTimeline';

type Tab = 'gaps' | 'recipes' | 'capacity' | 'roadmap' | 'runs';

export default function MigrationProjectDetail() {
  const params = useParams();
  const router = useRouter();
  const projectId = params.id as string;

  const [project, setProject] = useState<MigrationProject | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('gaps');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Recipes state
  const [allRecipes, setAllRecipes] = useState<MigrationRecipe[]>([]);
  const [recommendedRecipeIds, setRecommendedRecipeIds] = useState<string[]>([]);
  const [selectedRecipeIds, setSelectedRecipeIds] = useState<string[]>([]);
  const [savingRecipes, setSavingRecipes] = useState(false);

  // Capacity state
  const [savingCapacity, setSavingCapacity] = useState(false);

  // Runs state
  const [runs, setRuns] = useState<MigrationRun[]>([]);
  const [generatingRoadmap, setGeneratingRoadmap] = useState(false);
  const [executingStep, setExecutingStep] = useState(false);

  // Execution settings state
  const [targetRepoUrl, setTargetRepoUrl] = useState('');
  const [targetBranch, setTargetBranch] = useState('');

  // Custom recipe form state
  const [showRecipeForm, setShowRecipeForm] = useState(false);
  const [creatingRecipe, setCreatingRecipe] = useState(false);
  const [recipeForm, setRecipeForm] = useState({
    name: '',
    category: 'custom',
    description: '',
    priority: 50,
    tags: '',
    prerequisites: '',
    agent_instructions: '',
    source_framework: '',
    target_framework: '',
  });

  const loadProject = async () => {
    try {
      const p = await migrations.getProject(projectId);
      setProject(p);
      setSelectedRecipeIds(p.selected_recipes || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load project');
    } finally {
      setLoading(false);
    }
  };

  const loadRecipes = async () => {
    try {
      const [all, recommended] = await Promise.all([
        migrations.listRecipes(),
        migrations.getRecommendedRecipes(projectId),
      ]);
      setAllRecipes(all);
      setRecommendedRecipeIds(recommended.map(r => r.id));
    } catch (err) {
      console.error('Failed to load recipes:', err);
    }
  };

  const loadRuns = async () => {
    try {
      const res = await migrations.listRuns({ project_id: projectId });
      setRuns(res.runs);
    } catch (err) {
      console.error('Failed to load runs:', err);
    }
  };

  useEffect(() => {
    loadProject();
    loadRecipes();
    loadRuns();
  }, [projectId]);

  // Initialize execution settings from project
  useEffect(() => {
    if (project) {
      setTargetRepoUrl(project.source_repo_url || '');
      setTargetBranch(`migration/${project.name.toLowerCase().replace(/\s+/g, '-')}`);
    }
  }, [project?.id]);

  // Poll for updates when project is analyzing or runs are in progress
  useEffect(() => {
    const shouldPoll = project?.status === 'analyzing' ||
      runs.some(r => r.status === 'running' || r.status === 'queued');
    if (!shouldPoll) return;
    const interval = setInterval(() => {
      loadProject();
      loadRuns();
    }, 3000);
    return () => clearInterval(interval);
  }, [project?.status, runs]);

  const handleToggleRecipe = (recipeId: string) => {
    setSelectedRecipeIds(prev =>
      prev.includes(recipeId)
        ? prev.filter(id => id !== recipeId)
        : [...prev, recipeId]
    );
  };

  const handleSaveRecipes = async () => {
    setSavingRecipes(true);
    try {
      const updated = await migrations.setSelectedRecipes(projectId, selectedRecipeIds);
      setProject(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingRecipes(false);
    }
  };

  const handleCreateRecipe = async () => {
    setCreatingRecipe(true);
    try {
      await migrations.createCustomRecipe({
        name: recipeForm.name,
        category: recipeForm.category,
        description: recipeForm.description,
        priority: recipeForm.priority,
        tags: recipeForm.tags.split(',').map(t => t.trim()).filter(Boolean),
        prerequisites: recipeForm.prerequisites.split(',').map(t => t.trim()).filter(Boolean),
        agent_instructions: recipeForm.agent_instructions,
        source_framework: recipeForm.source_framework,
        target_framework: recipeForm.target_framework,
      });
      setShowRecipeForm(false);
      setRecipeForm({ name: '', category: 'custom', description: '', priority: 50, tags: '', prerequisites: '', agent_instructions: '', source_framework: '', target_framework: '' });
      await loadRecipes();
    } catch (err: any) {
      setError(err.message || 'Failed to create recipe');
    } finally {
      setCreatingRecipe(false);
    }
  };

  const handleSaveCapacity = async (target: Record<string, any>) => {
    setSavingCapacity(true);
    try {
      const updated = await migrations.updateCapacityTarget(projectId, target);
      setProject(updated);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSavingCapacity(false);
    }
  };

  const handleGenerateRoadmap = async () => {
    setGeneratingRoadmap(true);
    try {
      const run = await migrations.generateRoadmap(projectId);
      setRuns(prev => [run, ...prev]);
      setActiveTab('roadmap');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setGeneratingRoadmap(false);
    }
  };

  const handleExecuteStep = async (stepIndex: number) => {
    if (runs.length === 0) return;
    setExecutingStep(true);
    try {
      await migrations.executeStep(runs[0].id, stepIndex, targetBranch, targetRepoUrl);
      await loadRuns();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setExecutingStep(false);
    }
  };

  const handleExecuteAll = async () => {
    if (runs.length === 0) return;
    try {
      await migrations.executeRun(runs[0].id, targetBranch, targetRepoUrl);
      await loadRuns();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleReanalyze = async () => {
    try {
      await migrations.analyzeProject(projectId);
      await loadProject();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Delete this migration project?')) return;
    try {
      await migrations.deleteProject(projectId);
      router.push('/migration');
    } catch (err: any) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-8 text-center">
        <p className="text-gray-500">Project not found</p>
        <Link href="/migration" className="text-indigo-600 text-sm hover:underline mt-2 inline-block">
          Back to Migration
        </Link>
      </div>
    );
  }

  const latestRun = runs[0] || null;

  const TABS: { key: Tab; label: string; count?: number }[] = [
    { key: 'gaps', label: project.migration_mode === 'database' ? 'Schema Analysis' : project.migration_mode === 'improvement' ? 'Analysis' : 'Gap Analysis' },
    { key: 'recipes', label: 'Recipe Builder' },
    { key: 'capacity', label: 'Capacity' },
    { key: 'roadmap', label: 'Roadmap', count: latestRun?.roadmap_steps?.length },
    { key: 'runs', label: 'Runs', count: runs.length },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/migration" className="text-gray-400 hover:text-gray-600 text-sm">&larr;</Link>
            <h1 className="text-xl font-bold text-gray-900">{project.name}</h1>
            <MigrationStatusBadge status={project.status} />
            {project.migration_mode === 'improvement' && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-700">
                improvement
              </span>
            )}
            {project.migration_mode === 'database' && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-cyan-100 text-cyan-700">
                database
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-500">
            {project.migration_mode === 'database' ? (
              <>
                {project.config?.source_db && (
                  <span>Source: {project.config.source_db.engine}://{project.config.source_db.host}/{project.config.source_db.database}</span>
                )}
                {project.config?.destination_db && (
                  <span>Dest: {project.config.destination_db.engine}://{project.config.destination_db.host}/{project.config.destination_db.database}</span>
                )}
              </>
            ) : (
              <>
                {project.source_repo_url && <span>Source: {project.source_repo_url}</span>}
                {project.reference_repo_url && <span>Ref: {project.reference_repo_url}</span>}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {project.status === 'analyzed' && (
            <button
              onClick={handleReanalyze}
              className="px-3 py-1.5 text-xs text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Re-analyze
            </button>
          )}
          <button
            onClick={handleDelete}
            className="px-3 py-1.5 text-xs text-red-600 border border-red-200 rounded-md hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm mb-4">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-500 hover:text-red-700">&#x2715;</button>
        </div>
      )}

      {/* Analyzing spinner */}
      {project.status === 'analyzing' && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4 flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-blue-700">
            {project.migration_mode === 'database'
              ? 'Introspecting database schema...'
              : project.migration_mode === 'improvement'
                ? 'Running improvement analysis on repository...'
                : 'Analyzing source and reference repositories...'}
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="flex border-b border-gray-200">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors ${
                activeTab === tab.key
                  ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px]">{tab.count}</span>
              )}
            </button>
          ))}
        </div>

        <div className="p-4">
          {/* Gap Analysis Tab */}
          {activeTab === 'gaps' && (
            project.status === 'pending' ? (
              <div className="text-center py-8">
                <p className="text-sm text-gray-500 mb-3">Analysis has not been run yet.</p>
                <button
                  onClick={handleReanalyze}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700"
                >
                  Start Analysis
                </button>
              </div>
            ) : (
              <GapAnalysisPanel
                sourceProfile={project.source_profile}
                referenceProfile={project.reference_profile}
                gapAnalysis={project.gap_analysis}
                improvementAnalysis={project.improvement_analysis}
                migrationMode={project.migration_mode}
              />
            )
          )}

          {/* Recipe Builder Tab */}
          {activeTab === 'recipes' && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm text-gray-500">
                  Select migration recipes to include in your roadmap.
                  {recommendedRecipeIds.length > 0 && (
                    <> <span className="text-green-600 font-medium">{recommendedRecipeIds.length} recommended</span> based on gap analysis.</>
                  )}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowRecipeForm(!showRecipeForm)}
                    className="px-3 py-1.5 text-xs text-emerald-600 border border-emerald-200 rounded-md hover:bg-emerald-50"
                  >
                    {showRecipeForm ? 'Cancel' : '+ Create Recipe'}
                  </button>
                  <button
                    onClick={() => setSelectedRecipeIds(recommendedRecipeIds)}
                    className="px-3 py-1.5 text-xs text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50"
                  >
                    Select Recommended
                  </button>
                  <button
                    onClick={handleSaveRecipes}
                    disabled={savingRecipes}
                    className="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {savingRecipes ? 'Saving...' : `Save Selection (${selectedRecipeIds.length})`}
                  </button>
                </div>
              </div>

              {/* Custom Recipe Form */}
              {showRecipeForm && (
                <div className="mb-6 bg-emerald-50 border border-emerald-200 rounded-lg p-4">
                  <h4 className="text-sm font-semibold text-gray-900 mb-3">Create Custom Migration Recipe</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Recipe Name *</label>
                      <input
                        type="text"
                        value={recipeForm.name}
                        onChange={e => setRecipeForm({ ...recipeForm, name: e.target.value })}
                        placeholder="e.g. Nucleus → Photon: Config Server Migration"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
                      <select
                        value={recipeForm.category}
                        onChange={e => setRecipeForm({ ...recipeForm, category: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      >
                        <option value="custom">Custom</option>
                        <option value="java">Java</option>
                        <option value="dependencies">Dependencies</option>
                        <option value="config">Config</option>
                        <option value="docker">Docker</option>
                        <option value="k8s">Kubernetes</option>
                        <option value="cicd">CI/CD</option>
                        <option value="observability">Observability</option>
                        <option value="security">Security</option>
                        <option value="testing">Testing</option>
                        <option value="quality">Quality</option>
                        <option value="database">Database</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Source Framework</label>
                      <input
                        type="text"
                        value={recipeForm.source_framework}
                        onChange={e => setRecipeForm({ ...recipeForm, source_framework: e.target.value })}
                        placeholder="e.g. Nucleus, JISI"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Target Framework</label>
                      <input
                        type="text"
                        value={recipeForm.target_framework}
                        onChange={e => setRecipeForm({ ...recipeForm, target_framework: e.target.value })}
                        placeholder="e.g. Photon"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Priority (0-100)</label>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={recipeForm.priority}
                        onChange={e => setRecipeForm({ ...recipeForm, priority: parseInt(e.target.value) || 50 })}
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Tags (comma-separated)</label>
                      <input
                        type="text"
                        value={recipeForm.tags}
                        onChange={e => setRecipeForm({ ...recipeForm, tags: e.target.value })}
                        placeholder="nucleus, photon, config, framework-migration"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                      <textarea
                        value={recipeForm.description}
                        onChange={e => setRecipeForm({ ...recipeForm, description: e.target.value })}
                        placeholder="What this recipe migrates and why..."
                        rows={2}
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Agent Instructions (step-by-step)</label>
                      <textarea
                        value={recipeForm.agent_instructions}
                        onChange={e => setRecipeForm({ ...recipeForm, agent_instructions: e.target.value })}
                        placeholder={"1. Find all Nucleus config properties...\n2. Replace with Photon equivalents...\n3. Update application.yml..."}
                        rows={5}
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm font-mono"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Prerequisites (recipe IDs, comma-separated)</label>
                      <input
                        type="text"
                        value={recipeForm.prerequisites}
                        onChange={e => setRecipeForm({ ...recipeForm, prerequisites: e.target.value })}
                        placeholder="e.g. nucleus_to_photon_parent_pom"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                  </div>
                  <div className="mt-3 flex justify-end">
                    <button
                      onClick={handleCreateRecipe}
                      disabled={!recipeForm.name || creatingRecipe}
                      className="px-4 py-2 bg-emerald-600 text-white text-sm rounded-md hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {creatingRecipe ? 'Creating...' : 'Create Recipe'}
                    </button>
                  </div>
                </div>
              )}

              <RecipeGrid
                recipes={allRecipes}
                selectedIds={selectedRecipeIds}
                recommendedIds={recommendedRecipeIds}
                onToggle={handleToggleRecipe}
              />
            </div>
          )}

          {/* Capacity Tab */}
          {activeTab === 'capacity' && (
            <CapacityForm
              capacityCurrent={project.capacity_current}
              capacityTarget={project.capacity_target}
              onSave={handleSaveCapacity}
              saving={savingCapacity}
            />
          )}

          {/* Roadmap Tab */}
          {activeTab === 'roadmap' && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm text-gray-500">
                  {latestRun
                    ? `Roadmap with ${latestRun.roadmap_steps?.length || 0} steps`
                    : 'Generate a roadmap from your selected recipes.'}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleGenerateRoadmap}
                    disabled={generatingRoadmap || selectedRecipeIds.length === 0}
                    className="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {generatingRoadmap ? 'Generating...' : 'Generate Roadmap'}
                  </button>
                  {latestRun && latestRun.status === 'queued' && (
                    <button
                      onClick={handleExecuteAll}
                      className="px-3 py-1.5 text-xs bg-green-600 text-white rounded-md hover:bg-green-700"
                    >
                      Execute All
                    </button>
                  )}
                </div>
              </div>

              {/* Execution Settings */}
              {latestRun && (latestRun.status === 'queued' || latestRun.status === 'paused') && (
                <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <h4 className="text-sm font-semibold text-blue-900 mb-2">
                    Execution Settings &mdash; Where should changes be applied?
                  </h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Repository URL</label>
                      <input
                        value={targetRepoUrl}
                        onChange={e => setTargetRepoUrl(e.target.value)}
                        className="w-full px-3 py-2 border rounded-md text-sm"
                        placeholder="https://bitbucket.org/..."
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Target Branch</label>
                      <input
                        value={targetBranch}
                        onChange={e => setTargetBranch(e.target.value)}
                        className="w-full px-3 py-2 border rounded-md text-sm"
                        placeholder="migration/my-app"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Progress bar */}
              {latestRun && latestRun.status === 'running' && (
                <div className="mb-4">
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-indigo-600 transition-all"
                      style={{ width: `${latestRun.progress_pct}%` }}
                    />
                  </div>
                  <p className="text-xs text-gray-500 mt-1">{Math.round(latestRun.progress_pct)}% complete</p>
                </div>
              )}

              <RoadmapTimeline
                steps={latestRun?.roadmap_steps || []}
                currentStep={latestRun?.current_step || 0}
                onExecuteStep={handleExecuteStep}
                executing={executingStep}
              />
            </div>
          )}

          {/* Runs Tab */}
          {activeTab === 'runs' && (
            <div>
              {runs.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-8">
                  No migration runs yet. Generate a roadmap first.
                </p>
              ) : (
                <div className="space-y-3">
                  {runs.map(run => (
                    <div key={run.id} className="bg-white border border-gray-200 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900">Run {run.id.slice(0, 8)}</span>
                          <MigrationStatusBadge status={run.status} />
                        </div>
                        <span className="text-xs text-gray-400">
                          {new Date(run.created_at).toLocaleString()}
                        </span>
                      </div>

                      {/* Progress */}
                      {(run.status === 'running' || run.status === 'completed') && (
                        <div className="mb-2">
                          <div className="w-full bg-gray-200 rounded-full h-1.5">
                            <div
                              className={`h-1.5 rounded-full transition-all ${
                                run.status === 'completed' ? 'bg-green-600' : 'bg-indigo-600'
                              }`}
                              style={{ width: `${run.progress_pct}%` }}
                            />
                          </div>
                        </div>
                      )}

                      <div className="flex items-center gap-3 text-xs text-gray-500">
                        <span>{run.roadmap_steps?.length || 0} steps</span>
                        <span>Step {run.current_step}/{run.roadmap_steps?.length || 0}</span>
                        {run.result_summary && <span>{run.result_summary}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
