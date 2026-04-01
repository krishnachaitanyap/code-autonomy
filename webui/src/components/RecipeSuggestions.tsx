'use client';

import type { MigrationRecipe } from '@/lib/api';

interface RecipeSuggestionsProps {
  /** IDs of recipes that were auto-suggested */
  suggestedIds: string[];
  /** All available recipes (for resolving names) */
  recipes: MigrationRecipe[];
  /** Currently selected recipe IDs (includes both manual and auto) */
  selectedIds: string[];
  /** Called when user toggles a suggested recipe */
  onToggle: (id: string) => void;
  /** Whether auto-suggest is enabled */
  enabled: boolean;
  /** Toggle auto-suggest on/off */
  onToggleEnabled: (enabled: boolean) => void;
}

export default function RecipeSuggestions({
  suggestedIds,
  recipes,
  selectedIds,
  onToggle,
  enabled,
  onToggleEnabled,
}: RecipeSuggestionsProps) {
  // Always show the toggle; show chips only when enabled and there are suggestions
  if (!enabled && suggestedIds.length === 0) {
    return (
      <div className="flex items-center gap-2 py-1">
        <label className="inline-flex items-center gap-1.5 cursor-pointer text-xs text-gray-400">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggleEnabled(e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
          />
          Auto-suggest
        </label>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 py-1.5 overflow-x-auto">
      {/* Toggle */}
      <label className="inline-flex items-center gap-1.5 cursor-pointer text-xs text-gray-500 flex-shrink-0">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggleEnabled(e.target.checked)}
          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
        />
        Auto-suggest
      </label>

      {enabled && suggestedIds.length > 0 && (
        <>
          <span className="text-xs text-amber-600 flex-shrink-0">Suggested:</span>
          {suggestedIds.map(id => {
            const recipe = recipes.find(r => r.id === id);
            if (!recipe) return null;
            const isSelected = selectedIds.includes(id);
            return (
              <button
                key={id}
                type="button"
                onClick={() => onToggle(id)}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium whitespace-nowrap transition-all ${
                  isSelected
                    ? 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-300'
                    : 'bg-gray-100 text-gray-400 ring-1 ring-gray-200'
                }`}
              >
                <span className="text-[10px]">{isSelected ? '\u2713' : '\u25CB'}</span>
                <span className="truncate max-w-[150px]">{recipe.name}</span>
              </button>
            );
          })}
        </>
      )}
    </div>
  );
}
