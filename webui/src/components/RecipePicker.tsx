'use client';

import { useState, useMemo } from 'react';
import type { MigrationRecipe } from '@/lib/api';

// ---------------------------------------------------------------------------
// Category metadata — consistent with migration RecipeGrid & RoadmapTimeline
// ---------------------------------------------------------------------------

const CATEGORY_META: Record<string, { icon: string; color: string; bg: string; ring: string }> = {
  java:          { icon: '\u2615',          color: 'text-red-700',     bg: 'bg-red-50',     ring: 'ring-red-200' },
  dependencies:  { icon: '\uD83D\uDCE6',   color: 'text-purple-700',  bg: 'bg-purple-50',  ring: 'ring-purple-200' },
  docker:        { icon: '\uD83D\uDC33',   color: 'text-blue-700',    bg: 'bg-blue-50',    ring: 'ring-blue-200' },
  k8s:           { icon: '\u2638\uFE0F',    color: 'text-orange-700',  bg: 'bg-orange-50',  ring: 'ring-orange-200' },
  cicd:          { icon: '\uD83D\uDE80',    color: 'text-green-700',   bg: 'bg-green-50',   ring: 'ring-green-200' },
  config:        { icon: '\u2699\uFE0F',    color: 'text-teal-700',    bg: 'bg-teal-50',    ring: 'ring-teal-200' },
  observability: { icon: '\uD83D\uDCCA',    color: 'text-cyan-700',    bg: 'bg-cyan-50',    ring: 'ring-cyan-200' },
  security:      { icon: '\uD83D\uDD12',    color: 'text-yellow-700',  bg: 'bg-yellow-50',  ring: 'ring-yellow-200' },
  testing:       { icon: '\uD83E\uDDEA',    color: 'text-emerald-700', bg: 'bg-emerald-50', ring: 'ring-emerald-200' },
  quality:       { icon: '\u2728',          color: 'text-pink-700',    bg: 'bg-pink-50',    ring: 'ring-pink-200' },
  database:      { icon: '\uD83D\uDDC4\uFE0F', color: 'text-cyan-700', bg: 'bg-cyan-50',  ring: 'ring-cyan-200' },
  custom:        { icon: '\uD83D\uDEE0\uFE0F', color: 'text-indigo-700', bg: 'bg-indigo-50', ring: 'ring-indigo-200' },
};

const DEFAULT_META = { icon: '\uD83D\uDCCC', color: 'text-gray-700', bg: 'bg-gray-50', ring: 'ring-gray-200' };

function getCategoryMeta(category: string) {
  return CATEGORY_META[category] || DEFAULT_META;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RecipePickerProps {
  recipes: MigrationRecipe[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  /** Accent color scheme — matches the page theme */
  accent?: 'indigo' | 'teal';
}

export default function RecipePicker({ recipes, selectedIds, onChange, accent = 'indigo' }: RecipePickerProps) {
  const [expanded, setExpanded] = useState(false);
  const [search, setSearch] = useState('');
  const [filterCategory, setFilterCategory] = useState<string | null>(null);

  const accentStyles = accent === 'teal'
    ? { selected: 'border-teal-500 bg-teal-50/60 ring-1 ring-teal-400', check: 'text-teal-600', badge: 'bg-teal-600', badgeText: 'text-white', clearBtn: 'text-teal-600 hover:text-teal-800' }
    : { selected: 'border-indigo-500 bg-indigo-50/60 ring-1 ring-indigo-400', check: 'text-indigo-600', badge: 'bg-indigo-600', badgeText: 'text-white', clearBtn: 'text-indigo-600 hover:text-indigo-800' };

  // Group recipes by category
  const { categories, filtered } = useMemo(() => {
    const cats = new Set<string>();
    recipes.forEach(r => cats.add(r.category));

    let list = recipes;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(r =>
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q) ||
        r.tags?.some(t => t.toLowerCase().includes(q))
      );
    }
    if (filterCategory) {
      list = list.filter(r => r.category === filterCategory);
    }
    return { categories: Array.from(cats).sort(), filtered: list };
  }, [recipes, search, filterCategory]);

  // Group filtered recipes by category
  const grouped = useMemo(() => {
    const groups: Record<string, MigrationRecipe[]> = {};
    for (const r of filtered) {
      if (!groups[r.category]) groups[r.category] = [];
      groups[r.category].push(r);
    }
    return groups;
  }, [filtered]);

  function toggle(id: string) {
    onChange(
      selectedIds.includes(id)
        ? selectedIds.filter(x => x !== id)
        : [...selectedIds, id]
    );
  }

  if (recipes.length === 0) return null;

  // --- Collapsed: compact trigger bar ---
  if (!expanded) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 hover:border-gray-300 transition-all"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          Recipes
        </button>

        {/* Selected recipe pills */}
        {selectedIds.length > 0 && (
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {selectedIds.map(id => {
              const recipe = recipes.find(r => r.id === id);
              if (!recipe) return null;
              const meta = getCategoryMeta(recipe.category);
              return (
                <span
                  key={id}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${meta.bg} ${meta.color} ring-1 ${meta.ring}`}
                >
                  <span>{meta.icon}</span>
                  <span className="truncate max-w-[120px]">{recipe.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); toggle(id); }}
                    className="ml-0.5 hover:opacity-70"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </span>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // --- Expanded: full recipe picker panel ---
  return (
    <div className="border border-gray-200 rounded-xl bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <span className="text-sm font-semibold text-gray-700">Select Recipes</span>
          {selectedIds.length > 0 && (
            <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold ${accentStyles.badge} ${accentStyles.badgeText}`}>
              {selectedIds.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className={`text-xs font-medium ${accentStyles.clearBtn}`}
            >
              Clear all
            </button>
          )}
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="p-1 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Search + Category filter bar */}
      <div className="px-4 py-2 border-b border-gray-100 flex flex-col sm:flex-row gap-2">
        {/* Search */}
        <div className="relative flex-1">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search recipes..."
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-400 focus:border-indigo-400"
          />
        </div>
        {/* Category pills */}
        <div className="flex items-center gap-1 overflow-x-auto">
          <button
            type="button"
            onClick={() => setFilterCategory(null)}
            className={`px-2 py-1 rounded-md text-[11px] font-medium whitespace-nowrap transition-colors ${
              !filterCategory ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}
          >
            All
          </button>
          {categories.map(cat => {
            const meta = getCategoryMeta(cat);
            const active = filterCategory === cat;
            return (
              <button
                key={cat}
                type="button"
                onClick={() => setFilterCategory(active ? null : cat)}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium whitespace-nowrap transition-colors ${
                  active ? `${meta.bg} ${meta.color} ring-1 ${meta.ring}` : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                <span className="text-xs">{meta.icon}</span>
                <span className="capitalize">{cat}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Recipe cards — grouped by category */}
      <div className="max-h-64 overflow-y-auto px-4 py-3 space-y-4">
        {Object.keys(grouped).length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-4">No recipes match your search.</p>
        ) : (
          Object.entries(grouped).map(([category, catRecipes]) => {
            const meta = getCategoryMeta(category);
            return (
              <div key={category}>
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="text-sm">{meta.icon}</span>
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{category}</h4>
                  <span className="text-[10px] text-gray-400">({catRecipes.length})</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {catRecipes.map(recipe => {
                    const selected = selectedIds.includes(recipe.id);
                    const toolCount = recipe.tool_ids?.length || 0;
                    return (
                      <button
                        key={recipe.id}
                        type="button"
                        onClick={() => toggle(recipe.id)}
                        className={`group relative flex items-start gap-2.5 p-2.5 rounded-lg border text-left transition-all ${
                          selected
                            ? accentStyles.selected
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50/80'
                        }`}
                      >
                        {/* Checkbox */}
                        <div className={`flex-shrink-0 w-4 h-4 mt-0.5 rounded border-2 flex items-center justify-center transition-colors ${
                          selected
                            ? `${accent === 'teal' ? 'border-teal-500 bg-teal-500' : 'border-indigo-500 bg-indigo-500'}`
                            : 'border-gray-300 group-hover:border-gray-400'
                        }`}>
                          {selected && (
                            <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium text-gray-900 truncate">{recipe.name}</span>
                            {recipe.is_custom && (
                              <span className="flex-shrink-0 px-1 py-0.5 rounded text-[9px] font-semibold bg-indigo-100 text-indigo-600">
                                CUSTOM
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-gray-500 line-clamp-2 mt-0.5 leading-relaxed">
                            {recipe.description}
                          </p>
                          {/* Meta row */}
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${meta.bg} ${meta.color}`}>
                              P{recipe.priority}
                            </span>
                            {toolCount > 0 && (
                              <span className="inline-flex items-center gap-0.5 text-[10px] text-gray-400">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
                                </svg>
                                {toolCount} tool{toolCount !== 1 ? 's' : ''}
                              </span>
                            )}
                            {recipe.tags?.length > 0 && (
                              <span className="text-[10px] text-gray-400 truncate">
                                {recipe.tags.slice(0, 3).join(', ')}
                              </span>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer — selected summary */}
      {selectedIds.length > 0 && (
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-200 flex items-center gap-2 overflow-x-auto">
          <span className="text-[11px] text-gray-500 font-medium flex-shrink-0">Selected:</span>
          {selectedIds.map(id => {
            const recipe = recipes.find(r => r.id === id);
            if (!recipe) return null;
            const meta = getCategoryMeta(recipe.category);
            return (
              <span
                key={id}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ${meta.bg} ${meta.color} ring-1 ${meta.ring}`}
              >
                {meta.icon} {recipe.name}
                <button
                  type="button"
                  onClick={() => toggle(id)}
                  className="hover:opacity-60"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
