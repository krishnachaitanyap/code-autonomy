/**
 * Client-side recipe matching — scores recipes against a user prompt
 * using weighted token overlap.
 */

import type { MigrationRecipe } from '@/lib/api';

// Common English stopwords to filter out of prompts
const STOPWORDS = new Set([
  'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
  'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
  'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
  'into', 'through', 'during', 'before', 'after', 'above', 'below',
  'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
  'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
  'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
  'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
  'just', 'because', 'but', 'and', 'or', 'if', 'while', 'about', 'up',
  'this', 'that', 'these', 'those', 'it', 'its', 'i', 'me', 'my', 'we',
  'our', 'you', 'your', 'he', 'him', 'his', 'she', 'her', 'they', 'them',
  'their', 'what', 'which', 'who', 'whom', 'want', 'please', 'help',
]);

/** Tokenize text: lowercase, split on non-alphanumeric, remove stopwords, dedupe */
function tokenize(text: string): string[] {
  const tokens = text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(t => t.length >= 2 && !STOPWORDS.has(t));
  return Array.from(new Set(tokens));
}

/** Field-specific weights for scoring */
const FIELD_WEIGHTS = {
  tags: 5,
  category: 4,
  name: 3,
  description: 1,
} as const;

export interface RecipeMatch {
  recipe: MigrationRecipe;
  score: number;
}

/**
 * Score recipes against prompt tokens.
 * Returns top matches above threshold, sorted by score descending.
 */
export function suggestRecipes(
  prompt: string,
  recipes: MigrationRecipe[],
  options?: { threshold?: number; maxResults?: number },
): RecipeMatch[] {
  const threshold = options?.threshold ?? 0.15;
  const maxResults = options?.maxResults ?? 5;

  const tokens = tokenize(prompt);

  // Guard: need at least 3 meaningful tokens
  if (tokens.length < 3) return [];

  const scored: RecipeMatch[] = [];

  for (const recipe of recipes) {
    let score = 0;

    // Tags
    if (recipe.tags?.length) {
      const tagTokens = recipe.tags.flatMap(t => tokenize(t));
      for (const token of tokens) {
        if (tagTokens.includes(token)) score += FIELD_WEIGHTS.tags;
      }
    }

    // Category
    const catTokens = tokenize(recipe.category);
    for (const token of tokens) {
      if (catTokens.includes(token)) score += FIELD_WEIGHTS.category;
    }

    // Name
    const nameTokens = tokenize(recipe.name);
    for (const token of tokens) {
      if (nameTokens.includes(token)) score += FIELD_WEIGHTS.name;
    }

    // Description
    const descTokens = tokenize(recipe.description);
    for (const token of tokens) {
      if (descTokens.includes(token)) score += FIELD_WEIGHTS.description;
    }

    // Normalize by prompt token count
    const normalized = score / tokens.length;
    if (normalized >= threshold) {
      scored.push({ recipe, score: normalized });
    }
  }

  // Sort descending, take top N
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, maxResults);
}
