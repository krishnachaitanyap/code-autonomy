"""
MCP (Model Context Protocol) client — connects to MCP servers over stdio or SSE.

Provides two tool implementations:
- mcp_connect: Launch/connect to an MCP server and list its tools
- mcp_call: Invoke a tool on a connected MCP server

MCP servers are tracked per-session in a module-level registry. Each server
is identified by a user-chosen name (e.g. "filesystem", "db").
"""

import json
import logging
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory MCP server registry (per-process, session-scoped)
# ---------------------------------------------------------------------------

_servers: dict[str, "MCPServer"] = {}
_lock = threading.Lock()


class MCPServer:
    """Represents a connected MCP server."""

    def __init__(self, name: str, transport: str, command: str):
        self.name = name
        self.transport = transport  # "stdio" or "sse"
        self.command = command
        self.tools: list[dict] = []
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._sse_endpoint: str = ""  # For SSE: base URL for POST requests

    def next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def close(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _jsonrpc_request(method: str, params: Optional[dict], req_id: int) -> str:
    """Build a JSON-RPC 2.0 request string."""
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _jsonrpc_notification(method: str, params: Optional[dict] = None) -> str:
    """Build a JSON-RPC 2.0 notification (no id, no response expected)."""
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


# ---------------------------------------------------------------------------
# stdio transport
# ---------------------------------------------------------------------------

def _stdio_send_receive(process: subprocess.Popen, message: str, timeout: int = 30) -> dict:
    """Send a JSON-RPC message over stdio and read the response."""
    try:
        line = message + "\n"
        process.stdin.write(line)
        process.stdin.flush()

        # Read response with timeout
        import select
        start = time.time()
        response_line = ""
        while time.time() - start < timeout:
            if process.stdout.readable():
                ready = select.select([process.stdout], [], [], 1.0)
                if ready[0]:
                    response_line = process.stdout.readline()
                    if response_line.strip():
                        break
            if process.poll() is not None:
                stderr_out = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"MCP server process exited (code {process.returncode}): {stderr_out}")

        if not response_line.strip():
            raise TimeoutError(f"No response from MCP server within {timeout}s")

        return json.loads(response_line.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON response from MCP server: {e}\nRaw: {response_line[:500]}")


def _connect_stdio(server: MCPServer, timeout: int = 30) -> list[dict]:
    """Connect to an MCP server via stdio transport."""
    args = shlex.split(server.command)
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    server._process = process

    # Send initialize request
    init_msg = _jsonrpc_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "code-autonomy", "version": "1.0.0"},
    }, server.next_id())

    response = _stdio_send_receive(process, init_msg, timeout)

    if "error" in response:
        raise RuntimeError(f"MCP initialize failed: {response['error']}")

    # Send initialized notification
    notif = _jsonrpc_notification("notifications/initialized")
    process.stdin.write(notif + "\n")
    process.stdin.flush()

    # List tools
    list_msg = _jsonrpc_request("tools/list", {}, server.next_id())
    response = _stdio_send_receive(process, list_msg, timeout)

    if "error" in response:
        raise RuntimeError(f"MCP tools/list failed: {response['error']}")

    tools = response.get("result", {}).get("tools", [])
    server.tools = tools
    return tools


def _call_stdio(server: MCPServer, tool_name: str, arguments: dict, timeout: int = 60) -> str:
    """Call a tool on a stdio MCP server."""
    if not server._process or server._process.poll() is not None:
        raise RuntimeError(f"MCP server '{server.name}' is not running. Use mcp_connect to reconnect.")

    msg = _jsonrpc_request("tools/call", {
        "name": tool_name,
        "arguments": arguments,
    }, server.next_id())

    response = _stdio_send_receive(server._process, msg, timeout)

    if "error" in response:
        err = response["error"]
        return f"Error: MCP tool call failed — {err.get('message', err)}"

    result = response.get("result", {})
    content = result.get("content", [])

    # Format content items
    parts = []
    for item in content:
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif item.get("type") == "resource":
            uri = item.get("resource", {}).get("uri", "")
            text = item.get("resource", {}).get("text", "")
            parts.append(f"[Resource: {uri}]\n{text}")
        else:
            parts.append(json.dumps(item, indent=2))

    if result.get("isError"):
        return f"Error from MCP tool: {chr(10).join(parts)}"

    return "\n".join(parts) if parts else "(empty result)"


# ---------------------------------------------------------------------------
# SSE transport
# ---------------------------------------------------------------------------

def _connect_sse(server: MCPServer, timeout: int = 30) -> list[dict]:
    """Connect to an MCP server via HTTP+SSE transport."""
    base_url = server.command.rstrip("/")
    server._sse_endpoint = base_url

    # Send initialize
    init_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": server.next_id(),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "code-autonomy", "version": "1.0.0"},
        },
    }).encode()

    # POST to the endpoint
    req = urllib.request.Request(
        base_url,
        data=init_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        init_result = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"MCP SSE initialize failed: {e}")

    if "error" in init_result:
        raise RuntimeError(f"MCP initialize error: {init_result['error']}")

    # Send initialized notification
    notif = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }).encode()
    try:
        req = urllib.request.Request(base_url, data=notif, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Notifications don't require a response

    # List tools
    list_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": server.next_id(),
        "method": "tools/list",
        "params": {},
    }).encode()
    req = urllib.request.Request(base_url, data=list_payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        list_result = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"MCP tools/list failed: {e}")

    if "error" in list_result:
        raise RuntimeError(f"MCP tools/list error: {list_result['error']}")

    tools = list_result.get("result", {}).get("tools", [])
    server.tools = tools
    return tools


def _call_sse(server: MCPServer, tool_name: str, arguments: dict, timeout: int = 60) -> str:
    """Call a tool on an SSE MCP server."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": server.next_id(),
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode()

    req = urllib.request.Request(
        server._sse_endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read().decode())
    except Exception as e:
        return f"Error: MCP tool call failed — {e}"

    if "error" in result:
        err = result["error"]
        return f"Error: MCP tool call failed — {err.get('message', err)}"

    content = result.get("result", {}).get("content", [])
    parts = []
    for item in content:
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        else:
            parts.append(json.dumps(item, indent=2))

    if result.get("result", {}).get("isError"):
        return f"Error from MCP tool: {chr(10).join(parts)}"

    return "\n".join(parts) if parts else "(empty result)"


# ---------------------------------------------------------------------------
# Public API — tool dispatcher
# ---------------------------------------------------------------------------

def execute_mcp_tool(tool_name: str, args: dict, agent_config: Optional[dict] = None) -> str:
    """Execute an MCP tool (mcp_connect or mcp_call)."""
    if tool_name == "mcp_connect":
        return _handle_connect(args)
    if tool_name == "mcp_call":
        return _handle_call(args)
    return f"Error: Unknown MCP tool: {tool_name}"


def _handle_connect(args: dict) -> str:
    """Handle mcp_connect tool call."""
    transport = args.get("transport", "")
    command = args.get("command", "")
    server_name = args.get("server_name", "")

    if not transport or transport not in ("stdio", "sse"):
        return "Error: transport must be 'stdio' or 'sse'"
    if not command:
        return "Error: command is required"
    if not server_name:
        return "Error: server_name is required"

    # Close existing server with same name
    with _lock:
        if server_name in _servers:
            _servers[server_name].close()
            del _servers[server_name]

    server = MCPServer(server_name, transport, command)

    try:
        if transport == "stdio":
            tools = _connect_stdio(server)
        else:
            tools = _connect_sse(server)
    except Exception as e:
        server.close()
        return f"Error: Failed to connect to MCP server '{server_name}': {e}"

    with _lock:
        _servers[server_name] = server

    # Format tool list
    lines = [f"Connected to MCP server **{server_name}** ({transport}): {len(tools)} tool(s) available\n"]
    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        schema = t.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        lines.append(f"- **{name}**: {desc}")
        if props:
            param_strs = []
            for pname, pinfo in props.items():
                req_mark = " (required)" if pname in required else ""
                param_strs.append(f"  - `{pname}`: {pinfo.get('description', pinfo.get('type', ''))}{req_mark}")
            lines.extend(param_strs)
        lines.append("")

    return "\n".join(lines)


def _handle_call(args: dict) -> str:
    """Handle mcp_call tool call."""
    server_name = args.get("server_name", "")
    tool_name = args.get("tool_name", "")
    arguments = args.get("arguments", {})

    if not server_name:
        return "Error: server_name is required"
    if not tool_name:
        return "Error: tool_name is required"

    with _lock:
        server = _servers.get(server_name)

    if not server:
        available = list(_servers.keys()) if _servers else ["(none)"]
        return f"Error: MCP server '{server_name}' not connected. Available: {', '.join(available)}. Use mcp_connect first."

    # Validate tool exists
    tool_names = {t.get("name") for t in server.tools}
    if tool_name not in tool_names:
        return f"Error: Tool '{tool_name}' not found on server '{server_name}'. Available: {', '.join(sorted(tool_names))}"

    try:
        if server.transport == "stdio":
            return _call_stdio(server, tool_name, arguments)
        else:
            return _call_sse(server, tool_name, arguments)
    except Exception as e:
        return f"Error: MCP tool call failed — {e}"


def cleanup_mcp_servers():
    """Close all connected MCP servers. Called on session cleanup."""
    with _lock:
        for server in _servers.values():
            server.close()
        _servers.clear()
