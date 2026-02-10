"""
Shared utilities for AI-generated code parsing.
"""

import json


def parse_ai_changes(content: str) -> list[dict]:
    """Parse AI response into changes list. Handles markdown code blocks."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    try:
        data = json.loads(content)
        changes = data.get("changes", data) if isinstance(data, dict) else data
        return changes if isinstance(changes, list) else []
    except json.JSONDecodeError:
        return []
