'use client';

import type { MigrationRecipe } from '@/lib/api';

const CATEGORY_COLORS: Record<string, string> = {
  java: 'bg-red-100 text-red-700',
  dependencies: 'bg-purple-100 text-purple-700',
  docker: 'bg-blue-100 text-blue-700',
  k8s: 'bg-orange-100 text-orange-700',
  cicd: 'bg-green-100 text-green-700',
  config: 'bg-teal-100 text-teal-700',
  observability: 'bg-cyan-100 text-cyan-700',
  security: 'bg-yellow-100 text-yellow-700',
  testing: 'bg-emerald-100 text-emerald-700',
  quality: 'bg-pink-100 text-pink-700',
  database: 'bg-cyan-100 text-cyan-700',
  custom: 'bg-indigo-100 text-indigo-700',
};

interface RecipeGridProps {
  recipes: MigrationRecipe[];
  selectedIds: string[];
  recommendedIds: string[];
  onToggle: (recipeId: string) => void;
  onEdit?: (recipe: MigrationRecipe) => void;
  onDelete?: (recipeId: string) => void;
}

export default function RecipeGrid({ recipes, selectedIds, recommendedIds, onToggle, onEdit, onDelete }: RecipeGridProps) {
  // Group by category
  const groups: Record<string, MigrationRecipe[]> = {};
  for (const r of recipes) {
    if (!groups[r.category]) groups[r.category] = [];
    groups[r.category].push(r);
  }

  return (
    <div className="space-y-6">
      {Object.entries(groups).map(([category, categoryRecipes]) => (
        <div key={category}>
          <h3 className="text-sm font-semibold text-gray-700 mb-2 capitalize">{category}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {categoryRecipes.map(recipe => {
              const selected = selectedIds.includes(recipe.id);
              const recommended = recommendedIds.includes(recipe.id);
              const isCustom = !!recipe.is_custom;
              return (
                <div
                  key={recipe.id}
                  className={`relative border rounded-lg p-3 transition-all ${
                    selected
                      ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div
                    className="cursor-pointer"
                    onClick={() => onToggle(recipe.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => onToggle(recipe.id)}
                            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="text-sm font-medium text-gray-900 truncate">{recipe.name}</span>
                        </div>
                        <p className="text-xs text-gray-500 ml-6 line-clamp-2">{recipe.description}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${CATEGORY_COLORS[recipe.category] || 'bg-gray-100 text-gray-700'}`}>
                          {recipe.category}
                        </span>
                        {recommended && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700">
                            recommended
                          </span>
                        )}
                        {isCustom && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-100 text-indigo-700">
                            custom
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-2 ml-6">
                      <span className="text-[10px] text-gray-400">Priority: {recipe.priority}</span>
                      {recipe.prerequisites.length > 0 && (
                        <span className="text-[10px] text-gray-400">
                          Requires: {recipe.prerequisites.join(', ')}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Edit / Delete actions */}
                  {(onEdit || onDelete) && (
                    <div className="flex items-center gap-1.5 mt-2 ml-6 pt-2 border-t border-gray-100">
                      {onEdit && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onEdit(recipe); }}
                          className="px-2 py-0.5 text-[11px] font-medium text-indigo-600 bg-indigo-50 rounded hover:bg-indigo-100 transition-colors"
                        >
                          {isCustom ? 'Edit' : 'Edit (Override)'}
                        </button>
                      )}
                      {isCustom && onDelete && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onDelete(recipe.id); }}
                          className="px-2 py-0.5 text-[11px] font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
