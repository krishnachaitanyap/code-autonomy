"""
Shared utility for building recipe + tool context for agent sessions.

Used by both session flows (agent/plan/ask) and migration execution to
resolve recipe IDs into formatted prompt sections that include attached
tool instructions.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_recipe_context(recipe_ids: list[str]) -> str:
    """Build a formatted prompt section from recipe IDs with attached tools.

    Loads each recipe (custom DB recipes first, then built-in registry),
    resolves attached ``tool_ids`` to ``CustomTool`` records, and returns
    a structured prompt section the LLM can use.

    Returns an empty string when *recipe_ids* is empty or no recipes found.
    """
    if not recipe_ids:
        return ""

    recipes = _load_recipes(recipe_ids)
    if not recipes:
        return ""

    sections: list[str] = ["## Active Recipes\n"]

    for recipe in recipes:
        sections.append(f"### Recipe: {recipe['name']}")
        if recipe.get("description"):
            sections.append(recipe["description"])
        if recipe.get("agent_instructions"):
            sections.append(recipe["agent_instructions"])

        # Resolve attached tools
        tool_ids = recipe.get("tool_ids") or []
        if tool_ids:
            tools = _load_tools(tool_ids)
            if tools:
                sections.append("\n#### Attached Tools\n")
                for tool in tools:
                    tool_type = tool.get("tool_type", "agent")
                    sections.append(f"**@{tool['name']}** ({tool_type})")
                    if tool.get("goal"):
                        sections.append(f"Goal: {tool['goal']}")
                    if tool.get("agent_instructions"):
                        sections.append(f"Instructions: {tool['agent_instructions']}")
                    sections.append("")  # blank line between tools

        sections.append("")  # blank line between recipes

    return "\n".join(sections).strip()


def _load_recipes(recipe_ids: list[str]) -> list[dict]:
    """Load recipes by ID — checks custom DB recipes first, then built-in."""
    results: list[dict] = []
    remaining_ids = set(recipe_ids)

    # 1. Try custom recipes from DB
    try:
        from src.data.database import get_session
        from src.data.models import CustomMigrationRecipe

        with get_session() as db:
            customs = (
                db.query(CustomMigrationRecipe)
                .filter(CustomMigrationRecipe.id.in_(remaining_ids))
                .all()
            )
            for c in customs:
                results.append({
                    "id": c.id,
                    "name": c.name,
                    "category": c.category,
                    "description": c.description or "",
                    "agent_instructions": c.agent_instructions or "",
                    "tool_ids": c.tool_ids or [],
                })
                remaining_ids.discard(c.id)
    except Exception as exc:
        logger.debug("Could not load custom recipes from DB: %s", exc)

    # 2. Check built-in recipes for any remaining IDs
    if remaining_ids:
        try:
            from src.services.migration_recipes import RECIPES

            for recipe in RECIPES:
                if recipe.id in remaining_ids:
                    results.append({
                        "id": recipe.id,
                        "name": recipe.name,
                        "category": recipe.category,
                        "description": recipe.description,
                        "agent_instructions": recipe.agent_instructions,
                        "tool_ids": [],  # built-in recipes don't have tool_ids
                    })
                    remaining_ids.discard(recipe.id)
        except Exception as exc:
            logger.debug("Could not load built-in recipes: %s", exc)

    if remaining_ids:
        logger.warning("Recipes not found: %s", remaining_ids)

    return results


def _load_tools(tool_ids: list[str]) -> list[dict]:
    """Load CustomTool records by ID."""
    tools: list[dict] = []
    try:
        from src.services.tools_service import ToolsService

        svc = ToolsService()
        for tool_id in tool_ids:
            tool = svc.get_tool(tool_id)
            if tool:
                tools.append({
                    "name": tool.name,
                    "tool_type": tool.tool_type or "agent",
                    "goal": tool.goal or "",
                    "agent_instructions": tool.agent_instructions or "",
                })
            else:
                logger.warning("Tool not found: %s", tool_id)
    except Exception as exc:
        logger.debug("Could not load tools: %s", exc)
    return tools
