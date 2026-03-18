'use client';

import { useEffect, useState, useCallback } from 'react';
import { migrations, tools as toolsApi, type MigrationRecipe, type CustomTool } from '@/lib/api';

// ---------------------------------------------------------------------------
// Category metadata (mirrors RecipePicker)
// ---------------------------------------------------------------------------

const CATEGORY_META: Record<string, { icon: string; color: string; bg: string; ring: string; text: string }> = {
  java:          { icon: '\u2615',          color: 'text-red-700',     bg: 'bg-red-50',     ring: 'ring-red-200',     text: 'Java' },
  dependencies:  { icon: '\uD83D\uDCE6',   color: 'text-purple-700',  bg: 'bg-purple-50',  ring: 'ring-purple-200',  text: 'Dependencies' },
  docker:        { icon: '\uD83D\uDC33',   color: 'text-blue-700',    bg: 'bg-blue-50',    ring: 'ring-blue-200',    text: 'Docker' },
  k8s:           { icon: '\u2638\uFE0F',    color: 'text-orange-700',  bg: 'bg-orange-50',  ring: 'ring-orange-200',  text: 'Kubernetes' },
  cicd:          { icon: '\uD83D\uDE80',    color: 'text-green-700',   bg: 'bg-green-50',   ring: 'ring-green-200',   text: 'CI/CD' },
  config:        { icon: '\u2699\uFE0F',    color: 'text-teal-700',    bg: 'bg-teal-50',    ring: 'ring-teal-200',    text: 'Config' },
  observability: { icon: '\uD83D\uDCCA',    color: 'text-cyan-700',    bg: 'bg-cyan-50',    ring: 'ring-cyan-200',    text: 'Observability' },
  security:      { icon: '\uD83D\uDD12',    color: 'text-yellow-700',  bg: 'bg-yellow-50',  ring: 'ring-yellow-200',  text: 'Security' },
  testing:       { icon: '\uD83E\uDDEA',    color: 'text-emerald-700', bg: 'bg-emerald-50', ring: 'ring-emerald-200', text: 'Testing' },
  quality:       { icon: '\u2728',          color: 'text-pink-700',    bg: 'bg-pink-50',    ring: 'ring-pink-200',    text: 'Quality' },
  database:      { icon: '\uD83D\uDDC4\uFE0F', color: 'text-cyan-700', bg: 'bg-cyan-50',  ring: 'ring-cyan-200',   text: 'Database' },
  custom:        { icon: '\uD83D\uDEE0\uFE0F', color: 'text-indigo-700', bg: 'bg-indigo-50', ring: 'ring-indigo-200', text: 'Custom' },
};

const DEFAULT_META = { icon: '\uD83D\uDCCC', color: 'text-gray-700', bg: 'bg-gray-50', ring: 'ring-gray-200', text: 'Other' };

function getCat(category: string) {
  return CATEGORY_META[category] || DEFAULT_META;
}

const CATEGORIES = [
  'java', 'dependencies', 'docker', 'k8s', 'cicd', 'config',
  'observability', 'security', 'testing', 'quality', 'database', 'custom',
];

type ViewMode = 'grid' | 'list';

const EMPTY_FORM = {
  name: '',
  category: 'custom',
  description: '',
  priority: 3,
  tags: [] as string[],
  prerequisites: [] as string[],
  agent_instructions: '',
  source_framework: '',
  target_framework: '',
  tool_ids: [] as string[],
};

export default function RecipesPage() {
  const [recipes, setRecipes] = useState<MigrationRecipe[]>([]);
  const [customTools, setCustomTools] = useState<CustomTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [editingRecipe, setEditingRecipe] = useState<MigrationRecipe | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tagInput, setTagInput] = useState('');

  const loadData = useCallback(async () => {
    try {
      const [recipesRes, toolsRes] = await Promise.all([
        migrations.listRecipes(),
        toolsApi.list({ is_active: true }).catch(() => ({ tools: [] })),
      ]);
      setRecipes(recipesRes);
      setCustomTools(toolsRes.tools || []);
    } catch (err) {
      console.error('Failed to load recipes:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Filtering
  const filtered = recipes.filter(r => {
    if (filterCategory && r.category !== filterCategory) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.tags?.some(t => t.toLowerCase().includes(q))
      );
    }
    return true;
  });

  // Group by category
  const grouped: Record<string, MigrationRecipe[]> = {};
  for (const r of filtered) {
    if (!grouped[r.category]) grouped[r.category] = [];
    grouped[r.category].push(r);
  }

  // Stats
  const totalBuiltIn = recipes.filter(r => !r.is_custom).length;
  const totalCustom = recipes.filter(r => r.is_custom).length;
  const categoryCounts: Record<string, number> = {};
  recipes.forEach(r => { categoryCounts[r.category] = (categoryCounts[r.category] || 0) + 1; });

  // Form handlers
  const openCreate = () => {
    setEditingRecipe(null);
    setForm({ ...EMPTY_FORM });
    setTagInput('');
    setError('');
    setShowForm(true);
  };

  const openEdit = (recipe: MigrationRecipe) => {
    setEditingRecipe(recipe);
    setForm({
      name: recipe.name,
      category: recipe.category,
      description: recipe.description,
      priority: recipe.priority,
      tags: recipe.tags || [],
      prerequisites: recipe.prerequisites || [],
      agent_instructions: recipe.agent_instructions,
      source_framework: '',
      target_framework: '',
      tool_ids: recipe.tool_ids || [],
    });
    setTagInput('');
    setError('');
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (!form.agent_instructions.trim()) { setError('Agent instructions are required'); return; }
    setSaving(true);
    setError('');
    try {
      if (editingRecipe) {
        await migrations.updateCustomRecipe(editingRecipe.id, form);
      } else {
        await migrations.createCustomRecipe(form);
      }
      setShowForm(false);
      setEditingRecipe(null);
      loadData();
    } catch (err: any) {
      setError(err.message || 'Failed to save recipe');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await migrations.deleteCustomRecipe(id);
      loadData();
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (tag && !form.tags.includes(tag)) {
      setForm({ ...form, tags: [...form.tags, tag] });
      setTagInput('');
    }
  };

  const toggleTool = (toolId: string) => {
    setForm({
      ...form,
      tool_ids: form.tool_ids.includes(toolId)
        ? form.tool_ids.filter(t => t !== toolId)
        : [...form.tool_ids, toolId],
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <svg className="w-5 h-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recipes</h1>
          <p className="text-sm text-gray-500 mt-1">
            {totalBuiltIn} built-in, {totalCustom} custom recipes across {Object.keys(categoryCounts).length} categories
          </p>
        </div>
        <button
          onClick={openCreate}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          + New Recipe
        </button>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">Total</p>
          <p className="text-xl font-bold text-gray-900">{recipes.length}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">Built-in</p>
          <p className="text-xl font-bold text-blue-600">{totalBuiltIn}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">Custom</p>
          <p className="text-xl font-bold text-indigo-600">{totalCustom}</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 px-4 py-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide">Categories</p>
          <p className="text-xl font-bold text-gray-900">{Object.keys(categoryCounts).length}</p>
        </div>
      </div>

      {/* Filters + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search recipes by name, description, tag..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        {/* View toggle */}
        <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setViewMode('grid')}
            className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
              viewMode === 'grid' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Grid
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
              viewMode === 'list' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            List
          </button>
        </div>
      </div>

      {/* Category filter pills */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        <button
          onClick={() => setFilterCategory(null)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
            !filterCategory ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
          }`}
        >
          All ({recipes.length})
        </button>
        {CATEGORIES.filter(c => categoryCounts[c]).map(cat => {
          const meta = getCat(cat);
          const active = filterCategory === cat;
          return (
            <button
              key={cat}
              onClick={() => setFilterCategory(active ? null : cat)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                active ? `${meta.bg} ${meta.color} ring-1 ${meta.ring}` : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}
            >
              <span>{meta.icon}</span>
              <span>{meta.text}</span>
              <span className="text-[10px] opacity-60">({categoryCounts[cat]})</span>
            </button>
          );
        })}
      </div>

      {/* Recipe list */}
      {filtered.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <p className="text-sm text-gray-500">No recipes match your search.</p>
        </div>
      ) : viewMode === 'grid' ? (
        /* Grid view — grouped by category */
        <div className="space-y-6">
          {Object.entries(grouped).map(([category, catRecipes]) => {
            const meta = getCat(category);
            return (
              <div key={category}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-lg">{meta.icon}</span>
                  <h2 className="text-sm font-semibold text-gray-700">{meta.text}</h2>
                  <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px] font-medium">
                    {catRecipes.length}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {catRecipes.map(recipe => {
                    const toolCount = recipe.tool_ids?.length || 0;
                    return (
                      <div
                        key={recipe.id}
                        className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow cursor-pointer"
                        onClick={() => setExpandedId(expandedId === recipe.id ? null : recipe.id)}
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-gray-900 truncate">{recipe.name}</span>
                              {recipe.is_custom && (
                                <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-indigo-100 text-indigo-600">
                                  CUSTOM
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{recipe.description}</p>
                          </div>
                          <span className={`flex-shrink-0 ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold ${meta.bg} ${meta.color}`}>
                            P{recipe.priority}
                          </span>
                        </div>

                        {/* Meta */}
                        <div className="flex items-center gap-2 mt-3">
                          {toolCount > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] text-gray-400">
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
                              </svg>
                              {toolCount} tool{toolCount !== 1 ? 's' : ''}
                            </span>
                          )}
                          {recipe.tags?.length > 0 && (
                            <div className="flex gap-1 overflow-hidden">
                              {recipe.tags.slice(0, 3).map(tag => (
                                <span key={tag} className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px]">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Expanded detail */}
                        {expandedId === recipe.id && (
                          <div className="mt-3 pt-3 border-t border-gray-100 space-y-2" onClick={e => e.stopPropagation()}>
                            {recipe.agent_instructions && (
                              <div>
                                <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Instructions</label>
                                <pre className="bg-gray-50 rounded border border-gray-200 px-3 py-2 text-xs text-gray-700 whitespace-pre-wrap max-h-32 overflow-y-auto font-mono">
                                  {recipe.agent_instructions}
                                </pre>
                              </div>
                            )}
                            {recipe.prerequisites?.length > 0 && (
                              <div>
                                <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Prerequisites</label>
                                <div className="flex flex-wrap gap-1">
                                  {recipe.prerequisites.map(p => (
                                    <span key={p} className="px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded text-[10px]">{p}</span>
                                  ))}
                                </div>
                              </div>
                            )}
                            {recipe.is_custom && (
                              <div className="flex items-center gap-2 pt-2">
                                <button
                                  onClick={() => openEdit(recipe)}
                                  className="px-2.5 py-1 text-[11px] font-medium text-indigo-600 bg-indigo-50 rounded hover:bg-indigo-100 transition-colors"
                                >
                                  Edit
                                </button>
                                <button
                                  onClick={() => handleDelete(recipe.id)}
                                  className="px-2.5 py-1 text-[11px] font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
                                >
                                  Delete
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* List view */
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {filtered.map(recipe => {
            const meta = getCat(recipe.category);
            const toolCount = recipe.tool_ids?.length || 0;
            const isExpanded = expandedId === recipe.id;
            return (
              <div key={recipe.id}>
                <div
                  className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer"
                  onClick={() => setExpandedId(isExpanded ? null : recipe.id)}
                >
                  <span className="text-base flex-shrink-0">{meta.icon}</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${meta.bg} ${meta.color}`}>
                    {meta.text}
                  </span>
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-gray-900">{recipe.name}</span>
                    {recipe.description && (
                      <span className="text-xs text-gray-400 ml-2 truncate">{recipe.description}</span>
                    )}
                  </div>
                  {recipe.is_custom && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-indigo-100 text-indigo-600 flex-shrink-0">
                      CUSTOM
                    </span>
                  )}
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${meta.bg} ${meta.color} flex-shrink-0`}>
                    P{recipe.priority}
                  </span>
                  {toolCount > 0 && (
                    <span className="text-[10px] text-gray-400 flex-shrink-0">{toolCount} tool{toolCount !== 1 ? 's' : ''}</span>
                  )}
                  <svg
                    className={`w-4 h-4 text-gray-400 transition-transform flex-shrink-0 ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
                {isExpanded && (
                  <div className="px-4 pb-4 bg-gray-50 border-t border-gray-100">
                    <div className="grid grid-cols-2 gap-4 mt-3">
                      <div className="space-y-2">
                        {recipe.description && (
                          <div>
                            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Description</label>
                            <p className="text-sm text-gray-700">{recipe.description}</p>
                          </div>
                        )}
                        {recipe.agent_instructions && (
                          <div>
                            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Instructions</label>
                            <pre className="bg-white rounded border border-gray-200 px-3 py-2 text-xs text-gray-700 whitespace-pre-wrap max-h-40 overflow-y-auto font-mono">
                              {recipe.agent_instructions}
                            </pre>
                          </div>
                        )}
                      </div>
                      <div className="space-y-2">
                        {recipe.tags?.length > 0 && (
                          <div>
                            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Tags</label>
                            <div className="flex flex-wrap gap-1">
                              {recipe.tags.map(t => (
                                <span key={t} className="px-1.5 py-0.5 bg-gray-200 text-gray-700 rounded text-[10px]">{t}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {recipe.prerequisites?.length > 0 && (
                          <div>
                            <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Prerequisites</label>
                            <div className="flex flex-wrap gap-1">
                              {recipe.prerequisites.map(p => (
                                <span key={p} className="px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded text-[10px]">{p}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                    {recipe.is_custom && (
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-200">
                        <button
                          onClick={() => openEdit(recipe)}
                          className="px-2.5 py-1 text-[11px] font-medium text-indigo-600 bg-indigo-50 rounded hover:bg-indigo-100 transition-colors"
                        >
                          Edit
                        </button>
                        <div className="flex-1" />
                        <button
                          onClick={() => handleDelete(recipe.id)}
                          className="px-2.5 py-1 text-[11px] font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-start justify-center z-50 pt-16 px-4 overflow-y-auto">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mb-16">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">
                {editingRecipe ? 'Edit Recipe' : 'Create Custom Recipe'}
              </h2>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-gray-600">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal body */}
            <div className="px-6 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">{error}</div>
              )}

              {/* Name + Category + Priority */}
              <div className="grid grid-cols-6 gap-3">
                <div className="col-span-3">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                    placeholder="e.g. Migrate Spring Security to 6.x"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
                  <select
                    value={form.category}
                    onChange={e => setForm({ ...form, category: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {CATEGORIES.map(c => {
                      const m = getCat(c);
                      return <option key={c} value={c}>{m.icon} {m.text}</option>;
                    })}
                  </select>
                </div>
                <div className="col-span-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                  <input
                    type="number"
                    value={form.priority}
                    onChange={e => setForm({ ...form, priority: parseInt(e.target.value) || 3 })}
                    min={1}
                    max={5}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  placeholder="Short description of what this recipe does"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Agent Instructions */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Instructions</label>
                <textarea
                  value={form.agent_instructions}
                  onChange={e => setForm({ ...form, agent_instructions: e.target.value })}
                  placeholder={`Step 1: Analyze the current code...\nStep 2: Identify patterns to migrate...\nStep 3: Apply transformations...`}
                  rows={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Attached Tools */}
              {customTools.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Attached Tools</label>
                  <div className="flex flex-wrap gap-1.5">
                    {customTools.map(tool => (
                      <button
                        key={tool.id}
                        type="button"
                        onClick={() => toggleTool(tool.id)}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                          form.tool_ids.includes(tool.id)
                            ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
                            : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                        }`}
                      >
                        @{tool.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Tags */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Tags</label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={tagInput}
                    onChange={e => setTagInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                    placeholder="Add tag..."
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <button type="button" onClick={addTag} className="px-3 py-2 text-sm text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors">
                    Add
                  </button>
                </div>
                {form.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {form.tags.map(tag => (
                      <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs">
                        {tag}
                        <button onClick={() => setForm({ ...form, tags: form.tags.filter(t => t !== tag) })} className="hover:text-indigo-900">&times;</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Modal footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving...' : editingRecipe ? 'Update Recipe' : 'Create Recipe'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
