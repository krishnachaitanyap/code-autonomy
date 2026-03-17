"""
API routes for Custom Tools — user-defined agent tools for migration, chat, testing.
Also exposes built-in (system) tools from the agent tool registry.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    CustomToolCreate,
    CustomToolListResponse,
    CustomToolResponse,
    CustomToolUpdate,
    ResolvedModelInfo,
)
from src.services.tools_service import ToolsService

router = APIRouter(tags=["Tools"])
_service = ToolsService()


# ---------------------------------------------------------------------------
# Built-in tool registry (read-only, derived from src/agent/tools.py)
# ---------------------------------------------------------------------------

def _get_builtin_tools() -> list[dict]:
    """Return all built-in agent tools as structured dicts."""
    from src.agent.tools import (
        READ_TOOLS, WRITE_TOOLS, EXECUTION_TOOLS, COMPLETION_TOOLS,
        MEMORY_TOOLS, PLAN_TOOLS, ASK_COMPLETION_TOOLS, GCC_TOOLS,
    )
    try:
        from src.code_index import CODE_INDEX_TOOLS
    except Exception:
        CODE_INDEX_TOOLS = []

    def _extract(schema: dict, category: str) -> dict:
        fn = schema.get("function", {})
        params = fn.get("parameters", {}).get("properties", {})
        return {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "category": category,
            "parameters": {k: v.get("description", "") for k, v in params.items()},
            "required": fn.get("parameters", {}).get("required", []),
        }

    tools = []
    for s in READ_TOOLS:
        tools.append(_extract(s, "read"))
    for s in WRITE_TOOLS:
        tools.append(_extract(s, "write"))
    for s in EXECUTION_TOOLS:
        tools.append(_extract(s, "execution"))
    for s in MEMORY_TOOLS:
        tools.append(_extract(s, "memory"))
    for s in COMPLETION_TOOLS:
        tools.append(_extract(s, "completion"))
    for s in PLAN_TOOLS:
        tools.append(_extract(s, "plan"))
    for s in GCC_TOOLS:
        tools.append(_extract(s, "gcc"))
    for s in CODE_INDEX_TOOLS:
        tools.append(_extract(s, "code_index"))
    return tools


@router.get("/builtin")
async def list_builtin_tools():
    """Return all built-in (system) agent tools. These are read-only."""
    return {"tools": _get_builtin_tools()}


def _tool_to_response(tool) -> CustomToolResponse:
    # Resolve model config if linked
    resolved = None
    if tool.model_config_id and tool.model_config:
        mc = tool.model_config
        resolved = ResolvedModelInfo(
            id=mc.id, label=mc.label, provider=mc.provider, model=mc.model,
        )

    return CustomToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        tool_type=tool.tool_type,
        enabled_for_migration=tool.enabled_for_migration,
        enabled_for_chat=tool.enabled_for_chat,
        enabled_for_testing=tool.enabled_for_testing,
        agent_instructions=tool.agent_instructions,
        goal=tool.goal,
        allowed_tools=tool.allowed_tools or [],
        parameters=tool.parameters or {},
        tags=tool.tags or [],
        prerequisites=tool.prerequisites or [],
        max_turns=tool.max_turns,
        model=tool.model,
        model_config_id=tool.model_config_id,
        resolved_model=resolved,
        timeout_seconds=tool.timeout_seconds,
        is_active=tool.is_active,
        created_at=str(tool.created_at) if tool.created_at else None,
        updated_at=str(tool.updated_at) if tool.updated_at else None,
    )


@router.get("", response_model=CustomToolListResponse)
async def list_tools(
    enabled_for: Optional[str] = None,
    tool_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
):
    tools = _service.list_tools(
        enabled_for=enabled_for,
        tool_type=tool_type,
        is_active=is_active,
        limit=limit,
    )
    return CustomToolListResponse(
        tools=[_tool_to_response(t) for t in tools],
        total=len(tools),
    )


@router.get("/{tool_id}", response_model=CustomToolResponse)
async def get_tool(tool_id: str):
    tool = _service.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _tool_to_response(tool)


@router.post("", response_model=CustomToolResponse, status_code=201)
async def create_tool(body: CustomToolCreate):
    tool = _service.create_tool(
        name=body.name,
        description=body.description,
        tool_type=body.tool_type,
        enabled_for_migration=body.enabled_for_migration,
        enabled_for_chat=body.enabled_for_chat,
        enabled_for_testing=body.enabled_for_testing,
        agent_instructions=body.agent_instructions,
        goal=body.goal,
        allowed_tools=body.allowed_tools,
        parameters=body.parameters,
        tags=body.tags,
        prerequisites=body.prerequisites,
        max_turns=body.max_turns,
        model=body.model,
        model_config_id=body.model_config_id,
        timeout_seconds=body.timeout_seconds,
    )
    return _tool_to_response(tool)


@router.put("/{tool_id}", response_model=CustomToolResponse)
async def update_tool(tool_id: str, body: CustomToolUpdate):
    updates = body.model_dump(exclude_none=True)
    tool = _service.update_tool(tool_id, **updates)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _tool_to_response(tool)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(tool_id: str):
    if not _service.delete_tool(tool_id):
        raise HTTPException(status_code=404, detail="Tool not found")


@router.post("/{tool_id}/duplicate", response_model=CustomToolResponse, status_code=201)
async def duplicate_tool(tool_id: str):
    tool = _service.duplicate_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _tool_to_response(tool)
