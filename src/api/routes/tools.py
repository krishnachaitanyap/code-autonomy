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
        MCP_TOOLS,
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
    for s in MCP_TOOLS:
        tools.append(_extract(s, "mcp"))
    return tools


# ---------------------------------------------------------------------------
# Credential sanitization — follows ModelConfig.api_key_set pattern
# ---------------------------------------------------------------------------

def _sanitize_credential_config(cred_config: dict) -> tuple[dict, bool]:
    """Return (sanitized_config, credentials_set) — strip secrets, keep structure."""
    if not cred_config:
        return {}, False
    auth_type = cred_config.get("auth_type", "none")
    connection_type = cred_config.get("connection_type", "")

    # Nothing configured at all
    if auth_type == "none" and not connection_type:
        return {}, False

    sanitized: dict = {"auth_type": auth_type}
    if "config_section" in cred_config:
        sanitized["config_section"] = cred_config["config_section"]
    # Strip secret fields, add _set booleans
    for secret_field in ("password", "token", "keytab_path"):
        if cred_config.get(secret_field):
            sanitized[f"{secret_field}_set"] = True
    # Keep non-secret auth fields as-is
    for safe_field in ("username", "realm", "kdc", "principal", "base_url"):
        if cred_config.get(safe_field):
            sanitized[safe_field] = cred_config[safe_field]
    # Keep all connection detail fields (none are secrets)
    for conn_field in (
        "connection_type", "host", "port", "database", "schema",
        "service_name", "ssl_enabled", "extra_params",
        "mcp_transport", "mcp_command", "mcp_server_name",
    ):
        if cred_config.get(conn_field):
            sanitized[conn_field] = cred_config[conn_field]
    has_config = auth_type != "none" or bool(connection_type)
    return sanitized, has_config


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

    # Sanitize credential_config — never return secrets in API response
    sanitized_creds, creds_set = _sanitize_credential_config(tool.credential_config or {})

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
        credential_config=sanitized_creds,
        credentials_set=creds_set,
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
        credential_config=body.credential_config,
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


@router.post("/{tool_id}/test-credentials")
async def test_tool_credentials(tool_id: str):
    """Test whether the tool's configured credentials are functional."""
    tool = _service.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    cred_config = tool.credential_config or {}
    if not cred_config or cred_config.get("auth_type", "none") == "none":
        return {"status": "ok", "detail": "No authentication configured"}

    from src.agent.credentials import resolve_tool_credentials, test_credentials
    from src.config_loader import load_config

    try:
        config = load_config()
        agent_config = {"tool_credentials": config.get("tool_credentials", {})}
    except Exception:
        agent_config = {"tool_credentials": {}}

    resolved = resolve_tool_credentials(cred_config, agent_config)
    return test_credentials(resolved)
