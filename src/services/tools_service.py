"""
Service layer for Custom Tools — user-defined agent tools for migration, chat, testing.
"""

import logging
from typing import Optional

from src.data.database import get_session
from src.data.models import CustomTool, _uuid

logger = logging.getLogger(__name__)


class ToolsService:
    """CRUD operations for custom agent tools."""

    def list_tools(
        self,
        *,
        enabled_for: Optional[str] = None,
        tool_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
    ) -> list[CustomTool]:
        with get_session() as db:
            q = db.query(CustomTool)
            if enabled_for == "migration":
                q = q.filter(CustomTool.enabled_for_migration.is_(True))
            elif enabled_for == "chat":
                q = q.filter(CustomTool.enabled_for_chat.is_(True))
            elif enabled_for == "testing":
                q = q.filter(CustomTool.enabled_for_testing.is_(True))
            if tool_type:
                q = q.filter(CustomTool.tool_type == tool_type)
            if is_active is not None:
                q = q.filter(CustomTool.is_active.is_(is_active))
            return q.order_by(CustomTool.created_at.desc()).limit(limit).all()

    def get_tool(self, tool_id: str) -> Optional[CustomTool]:
        with get_session() as db:
            return db.get(CustomTool, tool_id)

    def create_tool(self, **kwargs) -> CustomTool:
        with get_session() as db:
            tool = CustomTool(id=_uuid(), **kwargs)
            db.add(tool)
            db.flush()
            db.expunge(tool)
        return tool

    def update_tool(self, tool_id: str, **kwargs) -> Optional[CustomTool]:
        with get_session() as db:
            tool = db.get(CustomTool, tool_id)
            if not tool:
                return None
            for key, value in kwargs.items():
                if value is not None and hasattr(tool, key):
                    setattr(tool, key, value)
            db.flush()
            db.expunge(tool)
        return tool

    def delete_tool(self, tool_id: str) -> bool:
        with get_session() as db:
            tool = db.get(CustomTool, tool_id)
            if not tool:
                return False
            db.delete(tool)
        return True

    def duplicate_tool(self, tool_id: str) -> Optional[CustomTool]:
        with get_session() as db:
            original = db.get(CustomTool, tool_id)
            if not original:
                return None
            clone = CustomTool(
                id=_uuid(),
                name=f"{original.name} (copy)",
                description=original.description,
                tool_type=original.tool_type,
                enabled_for_migration=original.enabled_for_migration,
                enabled_for_chat=original.enabled_for_chat,
                enabled_for_testing=original.enabled_for_testing,
                agent_instructions=original.agent_instructions,
                goal=original.goal,
                allowed_tools=original.allowed_tools,
                parameters=original.parameters,
                tags=original.tags,
                prerequisites=original.prerequisites,
                max_turns=original.max_turns,
                model=original.model,
                timeout_seconds=original.timeout_seconds,
                is_active=True,
            )
            db.add(clone)
            db.flush()
            db.expunge(clone)
        return clone
