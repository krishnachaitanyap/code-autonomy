"""API routes for MCP (Model Context Protocol) server management."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.data.database import get_session
from src.data.models import McpServer, CustomTool

logger = logging.getLogger(__name__)
router = APIRouter()


# Schemas
class McpServerCreate(BaseModel):
    name: str
    description: str = ""
    transport: str = "stdio"
    command: str = ""
    url: str = ""
    env_vars: dict = Field(default_factory=dict)
    auth_config: dict = Field(default_factory=dict)

class McpServerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    url: Optional[str] = None
    env_vars: Optional[dict] = None
    auth_config: Optional[dict] = None
    is_active: Optional[bool] = None

class McpServerResponse(BaseModel):
    id: str
    name: str
    description: str
    transport: str
    command: str
    url: str
    env_vars: dict
    auth_set: bool = False
    discovered_tools: list
    status: str
    last_connected_at: Optional[str] = None
    last_error: str
    is_active: bool
    tools_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _to_response(s: McpServer) -> McpServerResponse:
    auth = s.auth_config or {}
    auth_set = bool(auth.get("token") or auth.get("password") or auth.get("api_key"))
    return McpServerResponse(
        id=s.id,
        name=s.name,
        description=s.description,
        transport=s.transport,
        command=s.command,
        url=s.url,
        env_vars=s.env_vars or {},
        auth_set=auth_set,
        discovered_tools=s.discovered_tools or [],
        status=s.status,
        last_connected_at=str(s.last_connected_at) if s.last_connected_at else None,
        last_error=s.last_error or "",
        is_active=s.is_active,
        tools_count=len(s.discovered_tools or []),
        created_at=str(s.created_at) if s.created_at else None,
        updated_at=str(s.updated_at) if s.updated_at else None,
    )


@router.get("")
async def list_mcp_servers(
    status: Optional[str] = None,
    transport: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List all registered MCP servers."""
    with get_session() as db:
        q = db.query(McpServer)
        if status:
            q = q.filter(McpServer.status == status)
        if transport:
            q = q.filter(McpServer.transport == transport)
        if is_active is not None:
            q = q.filter(McpServer.is_active == is_active)
        servers = q.order_by(McpServer.created_at.desc()).limit(limit).all()
        return {"servers": [_to_response(s) for s in servers], "total": len(servers)}


@router.get("/{server_id}")
async def get_mcp_server(server_id: str):
    """Get a single MCP server by ID."""
    with get_session() as db:
        s = db.get(McpServer, server_id)
        if not s:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return _to_response(s)


@router.post("", status_code=201)
async def create_mcp_server(data: McpServerCreate):
    """Register a new MCP server."""
    with get_session() as db:
        # Check unique name
        existing = db.query(McpServer).filter(McpServer.name == data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"MCP server '{data.name}' already exists")
        s = McpServer(
            name=data.name,
            description=data.description,
            transport=data.transport,
            command=data.command,
            url=data.url,
            env_vars=data.env_vars,
            auth_config=data.auth_config,
        )
        db.add(s)
        db.flush()
        db.refresh(s)
        return _to_response(s)


@router.put("/{server_id}")
async def update_mcp_server(server_id: str, data: McpServerUpdate):
    """Update an MCP server's configuration."""
    with get_session() as db:
        s = db.get(McpServer, server_id)
        if not s:
            raise HTTPException(status_code=404, detail="MCP server not found")
        for field, value in data.dict(exclude_unset=True).items():
            if field == "auth_config" and value:
                # Merge auth — don't overwrite token with empty
                existing_auth = s.auth_config or {}
                for k, v in value.items():
                    if v:  # only overwrite non-empty values
                        existing_auth[k] = v
                s.auth_config = existing_auth
            else:
                setattr(s, field, value)
        db.flush()
        db.refresh(s)
        return _to_response(s)


@router.delete("/{server_id}")
async def delete_mcp_server(server_id: str):
    """Delete an MCP server. Warns if tools reference it."""
    with get_session() as db:
        s = db.get(McpServer, server_id)
        if not s:
            raise HTTPException(status_code=404, detail="MCP server not found")
        # Check references
        ref_count = db.query(CustomTool).filter(CustomTool.mcp_server_id == server_id).count()
        if ref_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete: {ref_count} tool(s) reference this MCP server. Unlink them first.",
            )
        db.delete(s)
        db.flush()
        return {"status": "deleted"}


@router.post("/{server_id}/discover")
async def discover_tools(server_id: str):
    """Connect to MCP server and discover available tools."""
    from datetime import datetime, timezone
    import time

    with get_session() as db:
        s = db.get(McpServer, server_id)
        if not s:
            raise HTTPException(status_code=404, detail="MCP server not found")

        start = time.time()
        try:
            # Try to use mcp_client if available
            discovered = []
            try:
                from src.agent.mcp_client import McpClient
                client = McpClient(
                    transport=s.transport,
                    command=s.command,
                    url=s.url,
                    env_vars=s.env_vars or {},
                    auth_config=s.auth_config or {},
                )
                discovered = client.discover_tools()
            except ImportError:
                # mcp_client not available — simulate discovery for now
                discovered = [
                    {"name": "placeholder", "description": "MCP client not installed. Install mcp package to enable discovery.", "inputSchema": {}},
                ]
            except Exception as exc:
                s.status = "error"
                s.last_error = str(exc)
                db.flush()
                latency = round((time.time() - start) * 1000)
                return {"status": "error", "error": str(exc), "tools_count": 0, "tools": [], "latency_ms": latency}

            s.discovered_tools = discovered
            s.status = "connected"
            s.last_connected_at = datetime.now(timezone.utc)
            s.last_error = ""
            db.flush()

            latency = round((time.time() - start) * 1000)
            return {
                "status": "connected",
                "tools_count": len(discovered),
                "tools": discovered,
                "latency_ms": latency,
            }

        except Exception as exc:
            s.status = "error"
            s.last_error = str(exc)
            db.flush()
            raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{server_id}/test")
async def test_connection(server_id: str):
    """Test connectivity to an MCP server."""
    import time

    with get_session() as db:
        s = db.get(McpServer, server_id)
        if not s:
            raise HTTPException(status_code=404, detail="MCP server not found")

    start = time.time()
    try:
        # Basic connectivity check
        if s.transport in ("sse", "streamable-http"):
            import requests
            resp = requests.get(s.url, timeout=10, verify=False)
            latency = round((time.time() - start) * 1000)
            return {"status": "ok", "latency_ms": latency, "http_status": resp.status_code}
        elif s.transport == "stdio":
            import subprocess
            cmd_parts = s.command.split()
            if cmd_parts:
                result = subprocess.run(
                    [cmd_parts[0], "--version"] if len(cmd_parts) == 1 else cmd_parts[:1] + ["--help"],
                    capture_output=True, text=True, timeout=10,
                )
                latency = round((time.time() - start) * 1000)
                return {"status": "ok", "latency_ms": latency, "detail": result.stdout[:200]}
        latency = round((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as exc:
        latency = round((time.time() - start) * 1000)
        return {"status": "error", "latency_ms": latency, "error": str(exc)}
