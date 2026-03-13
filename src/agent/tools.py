"""
Agent tools for Claude-Code-like capabilities.

Read tools  : read_file, grep, list_dir, find_files
Write tools : write_file, edit_file, delete_file
Exec tools  : run_command
Control     : task_complete

AI can call these iteratively to explore, modify, test, and fix code.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from src.code.search import grep, format_grep_results
from src.constants import SEARCH_EXTENSIONS, SKIP_DIRS
from src.agent.knowledge import WorkingMemory


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(repo_root: Path, requested: str) -> Optional[Path]:
    """Resolve path, ensure it stays within repo (no path traversal)."""
    requested = requested.strip().lstrip("/")
    if not requested:
        return repo_root
    full = (repo_root / requested).resolve()
    try:
        full.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return full


# ===================================================================
# READ TOOLS (unchanged from original)
# ===================================================================

def run_read_file(
    repo_root: Path,
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """Read file content, optionally a line range (1-based inclusive)."""
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: File not found or outside repo: {path}"
    if not target.is_file():
        return f"Error: Not a file: {path}"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"Error reading file: {e}"
    if start_line is not None or end_line is not None:
        s = max(0, (start_line or 1) - 1)
        e = end_line or len(lines)
        lines = lines[s:e]
    return "\n".join(lines)


def run_grep(
    repo_root: Path,
    pattern: str,
    path_filter: Optional[str] = None,
    context_lines: int = 2,
    max_results: int = 100,
) -> str:
    """Search for pattern in code files."""
    results = grep(
        str(repo_root),
        pattern,
        file_pattern=path_filter,
        context_lines=context_lines,
        max_results=max_results,
    )
    return format_grep_results(results)


def run_list_dir(repo_root: Path, path: str) -> str:
    """List directory contents (files and subdirs)."""
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: Directory not found or outside repo: {path}"
    if not target.is_dir():
        return f"Error: Not a directory: {path}"
    items = []
    for p in sorted(target.iterdir()):
        name = p.name
        if name.startswith(".") and name not in (".gitignore",):
            continue
        if p.is_dir():
            items.append(f"  [dir]  {name}/")
        else:
            items.append(f"  [file] {name}")
    return "\n".join(items) if items else "(empty)"


def run_find_files(
    repo_root: Path,
    extension: Optional[str] = None,
    pattern: Optional[str] = None,
) -> str:
    """Find files by extension (.java, .py) or name pattern (glob)."""
    target = Path(repo_root)
    if not target.exists():
        return "Error: Repo path not found"

    # Use session cache for directory listing
    from src.code.file_cache import get_session_cache
    cache = get_session_cache()

    ext_set = {extension} if extension else SEARCH_EXTENSIONS
    all_files = cache.list_directory(target, SKIP_DIRS, ext_set)

    found = []
    for f in all_files:
        rel = str(f.relative_to(target))
        if pattern:
            import fnmatch
            if not fnmatch.fnmatch(rel, pattern):
                continue
        found.append(rel)
    found.sort()
    return "\n".join(found[:200]) if found else "No files found"


# ===================================================================
# WRITE TOOLS (new)
# ===================================================================

def run_write_file(repo_root: Path, path: str, content: str) -> str:
    """Create a new file or completely overwrite an existing one."""
    if not path:
        return "Error: path is required"
    target = _safe_path(repo_root, path)
    if not target:
        return f"Error: Path outside repo: {path}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        # Invalidate cache after write
        from src.code.file_cache import get_session_cache
        get_session_cache().invalidate_file(target)
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def run_edit_file(
    repo_root: Path,
    path: str,
    old_string: str,
    new_string: str,
) -> str:
    """Surgical search-and-replace edit.

    *old_string* must appear exactly once in the file.
    It is replaced with *new_string* (use empty string to delete).
    """
    if not path:
        return "Error: path is required"
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: File not found: {path}"
    if not target.is_file():
        return f"Error: Not a file: {path}"
    if not old_string:
        return "Error: old_string is required (cannot be empty)"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    count = content.count(old_string)
    if count == 0:
        # Help the agent by showing the closest matching line
        hint = ""
        first_line = old_string.strip().split("\n")[0].strip() if old_string.strip() else ""
        if first_line and len(first_line) > 5:
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if first_line in line:
                    # Show the actual line so the agent can see the difference
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    snippet = "\n".join(f"  {start + j + 1}: {lines[start + j]}" for j in range(end - start))
                    hint = (
                        f"\nThe first line of old_string was found near line {i + 1}. "
                        f"Actual content around that line:\n{snippet}\n"
                        "Use read_file with start_line/end_line to get the exact text, then retry edit_file."
                    )
                    break
        return (
            f"Error: old_string not found in {path}. "
            "Make sure it matches exactly (including whitespace and indentation)."
            + hint
        )
    if count > 1:
        return (
            f"Error: old_string found {count} times in {path}. "
            "Include more surrounding context lines to make it unique."
        )

    new_content = content.replace(old_string, new_string, 1)
    try:
        target.write_text(new_content, encoding="utf-8")
        # Invalidate cache after edit
        from src.code.file_cache import get_session_cache
        get_session_cache().invalidate_file(target)
    except Exception as e:
        return f"Error writing file: {e}"
    return f"Edited {path}: replaced {len(old_string)} chars with {len(new_string)} chars"


def run_delete_file(repo_root: Path, path: str) -> str:
    """Delete a file from the repository."""
    if not path:
        return "Error: path is required"
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: File not found: {path}"
    if not target.is_file():
        return f"Error: Not a file: {path}"
    try:
        target.unlink()
        # Invalidate cache after delete
        from src.code.file_cache import get_session_cache
        get_session_cache().invalidate_file(target)
        return f"Deleted {path}"
    except Exception as e:
        return f"Error deleting file: {e}"


# ===================================================================
# EXECUTION TOOLS (new)
# ===================================================================

COMMAND_BLOCKLIST = {
    "rm -rf /",
    "rm -rf ~",
    "rm -rf .",
    "mkfs",
    "dd if=",
    "curl | sh",
    "curl |sh",
    "wget | sh",
    "wget |sh",
    "> /dev/sd",
    "shutdown",
    "reboot",
    "halt",
}

DEFAULT_ALLOWED_PREFIXES = [
    "pytest", "python -m pytest", "python -m unittest",
    "python", "pip install", "pip list",
    "mvn", "./mvnw", "gradle", "./gradlew",
    "npm test", "npm run", "npx",
    "java", "javac",
    "cat", "ls", "find", "grep", "wc", "head", "tail",
    "git status", "git diff", "git log",
]


def run_command(
    repo_root: Path,
    command: str,
    timeout: int = 120,
    agent_config: Optional[dict] = None,
) -> str:
    """Run a shell command sandboxed to the repository directory."""
    if not command or not command.strip():
        return "Error: command is required"

    timeout = min(timeout or 120, 300)
    cfg = agent_config or {}

    # Safety: blocklist
    cmd_lower = command.lower().strip()
    for blocked in COMMAND_BLOCKLIST:
        if blocked in cmd_lower:
            return f"Error: Command blocked for safety: {command}"

    # Safety: optional allowlist
    if cfg.get("command_allowlist_only"):
        allowed = cfg.get("allowed_command_prefixes") or DEFAULT_ALLOWED_PREFIXES
        if not any(cmd_lower.startswith(p.lower()) for p in allowed):
            return f"Error: Command not in allowlist. Allowed prefixes: {allowed}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "TERM": "dumb"},
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += "[stderr]\n" + result.stderr
        output += f"\n[exit code: {result.returncode}]"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error running command: {e}"


# ===================================================================
# TOOL SCHEMAS (OpenAI function-calling format)
# ===================================================================

def _tool(name: str, description: str, params: dict, required: list[str] | None = None) -> dict:
    """Build an OpenAI function-calling tool schema."""
    schema = {"type": "function", "function": {"name": name, "description": description,
              "parameters": {"type": "object", "properties": params}}}
    if required:
        schema["function"]["parameters"]["required"] = required
    return schema

# --- Read tool schemas ---

_READ_FILE_SCHEMA = _tool("read_file",
    "Read the contents of a file. Use path relative to repo root. Optionally specify start_line and end_line (1-based) to read a range.",
    {"path": {"type": "string", "description": "Relative file path (e.g., src/main/java/demo/App.java)"},
     "start_line": {"type": "integer", "description": "Optional start line (1-based)"},
     "end_line": {"type": "integer", "description": "Optional end line (1-based)"}},
    required=["path"])

_GREP_SCHEMA = _tool("grep",
    "Search for a regex pattern across code files. Returns matching lines with context.",
    {"pattern": {"type": "string", "description": "Regex pattern to search for"},
     "path_filter": {"type": "string", "description": "Optional file path filter (regex)"},
     "context_lines": {"type": "integer", "description": "Lines of context around matches (default 2)"}},
    required=["pattern"])

_LIST_DIR_SCHEMA = _tool("list_dir",
    "List contents of a directory. Use path relative to repo root. Use empty string for repo root.",
    {"path": {"type": "string", "description": "Relative directory path (empty for repo root)"}},
    required=["path"])

_FIND_FILES_SCHEMA = _tool("find_files",
    "Find files by extension or name pattern. Returns list of relative paths.",
    {"extension": {"type": "string", "description": "File extension (e.g., .java, .py)"},
     "pattern": {"type": "string", "description": "Optional glob pattern for file name"}})

# --- Write tool schemas ---

_WRITE_FILE_SCHEMA = _tool("write_file",
    "Create a new file or completely overwrite an existing file. Use for new files. For modifying existing files, prefer edit_file.",
    {"path": {"type": "string", "description": "Relative file path (e.g., src/utils.py)"},
     "content": {"type": "string", "description": "Complete file content to write"}},
    required=["path", "content"])

_EDIT_FILE_SCHEMA = _tool("edit_file",
    "Make a surgical edit to an existing file. Finds old_string (must appear exactly once) "
    "and replaces it with new_string. Include enough surrounding context lines in old_string "
    "to make the match unique. Whitespace and indentation must match exactly.",
    {"path": {"type": "string", "description": "Relative file path to edit"},
     "old_string": {"type": "string", "description": "Exact string to find (must appear exactly once)"},
     "new_string": {"type": "string", "description": "Replacement string (empty string to delete)"}},
    required=["path", "old_string", "new_string"])

_DELETE_FILE_SCHEMA = _tool("delete_file",
    "Delete a file from the repository.",
    {"path": {"type": "string", "description": "Relative file path to delete"}},
    required=["path"])

# --- Execution tool schemas ---

_RUN_COMMAND_SCHEMA = _tool("run_command",
    "Run a shell command in the repository directory. "
    "Use for running tests (pytest, mvn test), builds, linting, or inspecting output. "
    "Commands are sandboxed to the repo directory.",
    {"command": {"type": "string", "description": "Shell command (e.g., 'pytest -v', 'mvn test')"},
     "timeout": {"type": "integer", "description": "Timeout in seconds (default 120, max 300)"}},
    required=["command"])

# --- Completion tool schema ---

_TASK_COMPLETE_SCHEMA = _tool("task_complete",
    "Signal that all changes are done and verified. "
    "Call this when you have finished implementing, tested the changes, "
    "and are confident the task is complete.",
    {"summary": {"type": "string", "description": "Brief summary of changes made"},
     "files_changed": {"type": "array", "items": {"type": "string"},
                       "description": "List of file paths created, modified, or deleted"}},
    required=["summary", "files_changed"])

# --- Plan tool schemas ---

_PROPOSE_CHANGE_SCHEMA = _tool("propose_change",
    "Propose a file change without writing to disk. Use this in plan mode to accumulate changes for review.\n"
    "Actions: 'create' (new file), 'modify' (edit existing), 'delete' (remove file).\n"
    "For 'create': provide content (full file content).\n"
    "For 'modify': provide old_string + new_string for a surgical edit, or content for full replacement.\n"
    "For 'delete': only path and action are needed.",
    {"path": {"type": "string", "description": "Relative file path"},
     "action": {"type": "string", "enum": ["create", "modify", "delete"],
                "description": "Change action: create, modify, or delete"},
     "description": {"type": "string", "description": "Brief description of what this change does"},
     "content": {"type": "string", "description": "Full file content (for create, or full replacement on modify)"},
     "old_string": {"type": "string", "description": "Exact string to find (for modify with surgical edit)"},
     "new_string": {"type": "string", "description": "Replacement string (for modify with surgical edit)"}},
    required=["path", "action", "description"])

# --- Ask-mode completion schema ---

_ASK_TASK_COMPLETE_SCHEMA = _tool("task_complete",
    "Signal that you have answered the question. "
    "Provide your complete answer and list the files you consulted.",
    {"summary": {"type": "string", "description": "Brief summary of exploration done"},
     "answer": {"type": "string", "description": "Your complete answer to the user's question"},
     "sources": {"type": "array", "items": {"type": "string"},
                 "description": "List of file paths you consulted to answer"}},
    required=["answer", "sources"])

# --- Memory tool schemas ---

_UPDATE_MEMORY_SCHEMA = _tool("update_memory",
    "Write a note to working memory. Notes survive context compression and are "
    "saved to persistent knowledge when you call task_complete. "
    "Use well-known keys for structured knowledge:\n"
    "- 'project_overview': language, build tool, framework, test framework\n"
    "- 'key_patterns': naming conventions, architecture patterns, common idioms\n"
    "- 'file_notes': important files and what they contain\n"
    "Use any other key for ad-hoc notes.",
    {"key": {"type": "string", "description": "Note key (e.g., 'project_overview', 'key_patterns', 'file_notes')"},
     "content": {"type": "string", "description": "Note content (Markdown supported)"}},
    required=["key", "content"])

_READ_MEMORY_SCHEMA = _tool("read_memory",
    "Read all notes from working memory and any prior knowledge from previous runs.",
    {})

# --- GCC (Git Context Controller) tool schemas ---

_GCC_COMMIT_SCHEMA = _tool("gcc_commit",
    "Checkpoint your current progress. Creates a versioned snapshot with a summary "
    "of what was accomplished. Optionally mark as a milestone (e.g. 'tests passing', "
    "'initial exploration done').",
    {"summary": {"type": "string", "description": "Description of what was accomplished"},
     "milestone": {"type": "string", "description": "Optional milestone label (e.g. 'tests passing')"}},
    required=["summary"])

_GCC_BRANCH_SCHEMA = _tool("gcc_branch",
    "Create a new reasoning branch to explore an alternative approach. "
    "Branches are context-level (not code-level) — they create isolated note-spaces "
    "for exploratory reasoning without affecting working memory or conversation history.",
    {"name": {"type": "string", "description": "Branch name (e.g. 'alt-approach', 'refactor-idea')"},
     "purpose": {"type": "string", "description": "Why this branch is being created"}},
    required=["name", "purpose"])

_GCC_MERGE_SCHEMA = _tool("gcc_merge",
    "Merge a reasoning branch back into main, consolidating findings. "
    "Creates an auto-commit recording the merge.",
    {"branch_name": {"type": "string", "description": "Name of the branch to merge"}},
    required=["branch_name"])

_GCC_CONTEXT_SCHEMA = _tool("gcc_context",
    "Retrieve stored context at various levels of detail. "
    "Scopes: 'status' (short summary), 'main' (synthesized context), "
    "'commits' (full commit log), 'branch' (specific branch details), 'all' (everything).",
    {"scope": {"type": "string", "enum": ["status", "main", "commits", "branch", "all"],
               "description": "Level of detail to retrieve (default: status)"},
     "branch": {"type": "string", "description": "Branch name (required when scope='branch')"}})

GCC_TOOLS = [_GCC_COMMIT_SCHEMA, _GCC_BRANCH_SCHEMA, _GCC_MERGE_SCHEMA, _GCC_CONTEXT_SCHEMA]


def _gcc_enabled(agent_config: Optional[dict] = None) -> bool:
    """Check if GCC is enabled in agent config."""
    if agent_config is None:
        return False
    val = agent_config.get("gcc_enabled", False)
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


# ===================================================================
# Tool list builders
# ===================================================================

READ_TOOLS = [_READ_FILE_SCHEMA, _GREP_SCHEMA, _LIST_DIR_SCHEMA, _FIND_FILES_SCHEMA]
WRITE_TOOLS = [_WRITE_FILE_SCHEMA, _EDIT_FILE_SCHEMA, _DELETE_FILE_SCHEMA]
EXECUTION_TOOLS = [_RUN_COMMAND_SCHEMA]
COMPLETION_TOOLS = [_TASK_COMPLETE_SCHEMA]
MEMORY_TOOLS = [_UPDATE_MEMORY_SCHEMA, _READ_MEMORY_SCHEMA]
PLAN_TOOLS = [_PROPOSE_CHANGE_SCHEMA]
ASK_COMPLETION_TOOLS = [_ASK_TASK_COMPLETE_SCHEMA]

# Backward-compatible read-only tool list (used by old code paths)
AGENT_TOOLS = list(READ_TOOLS)


def _splunk_enabled(agent_config: Optional[dict] = None) -> bool:
    """Check if Splunk integration is enabled in agent config."""
    if agent_config is None:
        return False
    return bool(agent_config.get("splunk_enabled", False))


def _certs_enabled(agent_config: Optional[dict] = None) -> bool:
    """Check if certificate inspection tools are enabled in agent config."""
    if agent_config is None:
        return False
    return bool(agent_config.get("certs_enabled", False))


def build_agent_tools(agent_config: Optional[dict] = None, code_index: Optional["CodeIndex"] = None) -> list[dict]:
    """Build the full tool list for the new agent mode."""
    tools: list[dict] = []
    tools.extend(READ_TOOLS)
    tools.extend(WRITE_TOOLS)
    tools.extend(EXECUTION_TOOLS)
    tools.extend(MEMORY_TOOLS)
    tools.extend(COMPLETION_TOOLS)
    if _gcc_enabled(agent_config):
        tools.extend(GCC_TOOLS)
    if code_index is not None:
        from src.code_index import CODE_INDEX_TOOLS
        tools.extend(CODE_INDEX_TOOLS)
    if _splunk_enabled(agent_config):
        from src.splunk import SPLUNK_TOOLS
        tools.extend(SPLUNK_TOOLS)
    if _certs_enabled(agent_config):
        from src.certs import CERTS_TOOLS
        tools.extend(CERTS_TOOLS)
    return tools


def build_plan_tools(agent_config: Optional[dict] = None, code_index: Optional["CodeIndex"] = None) -> list[dict]:
    """Build the tool list for plan mode (read-only + propose_change + memory + completion)."""
    tools: list[dict] = []
    tools.extend(READ_TOOLS)
    tools.extend(PLAN_TOOLS)
    tools.extend(MEMORY_TOOLS)
    tools.extend(COMPLETION_TOOLS)
    if _gcc_enabled(agent_config):
        tools.extend(GCC_TOOLS)
    if code_index is not None:
        from src.code_index import CODE_INDEX_TOOLS
        tools.extend(CODE_INDEX_TOOLS)
    if _splunk_enabled(agent_config):
        from src.splunk import SPLUNK_TOOLS
        tools.extend(SPLUNK_TOOLS)
    if _certs_enabled(agent_config):
        from src.certs import CERTS_TOOLS
        tools.extend(CERTS_TOOLS)
    return tools


def build_ask_tools(agent_config: Optional[dict] = None, code_index: Optional["CodeIndex"] = None) -> list[dict]:
    """Build the tool list for ask mode (read-only + memory + answer completion)."""
    tools: list[dict] = []
    tools.extend(READ_TOOLS)
    tools.extend(MEMORY_TOOLS)
    tools.extend(ASK_COMPLETION_TOOLS)
    if _gcc_enabled(agent_config):
        tools.extend([_GCC_CONTEXT_SCHEMA, _GCC_COMMIT_SCHEMA])
    if code_index is not None:
        from src.code_index import CODE_INDEX_TOOLS
        tools.extend(CODE_INDEX_TOOLS)
    if _splunk_enabled(agent_config):
        from src.splunk import SPLUNK_TOOLS
        tools.extend(SPLUNK_TOOLS)
    if _certs_enabled(agent_config):
        from src.certs import CERTS_TOOLS
        tools.extend(CERTS_TOOLS)
    return tools


# ===================================================================
# Tool dispatcher
# ===================================================================

def execute_tool(
    repo_root: Path,
    tool_name: str,
    args: dict,
    changes_tracker: Optional[set] = None,
    agent_config: Optional[dict] = None,
    working_memory: Optional[WorkingMemory] = None,
    gcc_controller: Optional["GCCController"] = None,
    code_index: Optional["CodeIndex"] = None,
) -> str:
    """Execute a tool and return the result string.

    *changes_tracker*: if provided, paths of written/edited/deleted files
    are added to this set.
    *working_memory*: if provided, used by memory tools.
    *gcc_controller*: if provided, used by gcc_* tools.
    *code_index*: if provided, used by code_index tools.
    """
    repo = Path(repo_root)

    # --- GCC tools ---
    if tool_name == "gcc_commit":
        if gcc_controller is None:
            return "Error: GCC not enabled"
        wm_snapshot = working_memory.to_dict() if working_memory and not working_memory.is_empty() else {}
        return gcc_controller.commit(
            summary=args.get("summary", ""),
            working_memory=wm_snapshot,
            milestone=args.get("milestone", ""),
        )
    if tool_name == "gcc_branch":
        if gcc_controller is None:
            return "Error: GCC not enabled"
        return gcc_controller.branch(
            name=args.get("name", ""),
            purpose=args.get("purpose", ""),
        )
    if tool_name == "gcc_merge":
        if gcc_controller is None:
            return "Error: GCC not enabled"
        wm_snapshot = working_memory.to_dict() if working_memory and not working_memory.is_empty() else {}
        return gcc_controller.merge(
            branch_name=args.get("branch_name", ""),
            working_memory=wm_snapshot,
        )
    if tool_name == "gcc_context":
        if gcc_controller is None:
            return "Error: GCC not enabled"
        return gcc_controller.context(
            scope=args.get("scope", "status"),
            branch=args.get("branch", ""),
        )

    # --- Memory tools ---
    if tool_name == "update_memory":
        if working_memory is None:
            return "Error: working memory not available"
        return working_memory.update(args.get("key", ""), args.get("content", ""))

    if tool_name == "read_memory":
        if working_memory is None:
            return "(no working memory available)"
        return working_memory.read_all()

    # --- Read tools ---
    if tool_name == "read_file":
        return run_read_file(repo, args.get("path", ""), args.get("start_line"), args.get("end_line"))
    if tool_name == "grep":
        return run_grep(repo, args.get("pattern", ""), args.get("path_filter"), args.get("context_lines", 2))
    if tool_name == "list_dir":
        return run_list_dir(repo, args.get("path", ""))
    if tool_name == "find_files":
        return run_find_files(repo, args.get("extension"), args.get("pattern"))

    # --- Write tools ---
    if tool_name == "write_file":
        result = run_write_file(repo, args.get("path", ""), args.get("content", ""))
        if changes_tracker is not None and not result.startswith("Error"):
            changes_tracker.add(args.get("path", ""))
        return result

    if tool_name == "edit_file":
        result = run_edit_file(repo, args.get("path", ""), args.get("old_string", ""), args.get("new_string", ""))
        if changes_tracker is not None and not result.startswith("Error"):
            changes_tracker.add(args.get("path", ""))
        return result

    if tool_name == "delete_file":
        result = run_delete_file(repo, args.get("path", ""))
        if changes_tracker is not None and not result.startswith("Error"):
            changes_tracker.add(args.get("path", ""))
        return result

    # --- Execution tools ---
    if tool_name == "run_command":
        return run_command(repo, args.get("command", ""), args.get("timeout", 120), agent_config)

    # --- Code index tools ---
    if code_index is not None:
        from src.code_index import CODE_INDEX_TOOL_NAMES, execute_code_index_tool
        if tool_name in CODE_INDEX_TOOL_NAMES:
            return execute_code_index_tool(code_index, tool_name, args)

    # --- Splunk tools ---
    if tool_name in ("splunk_discover", "splunk_search", "splunk_stats", "splunk_saved_search", "splunk_ask"):
        splunk_cfg = {
            "splunk": (agent_config or {}).get("splunk_config", {}),
            "opensearch": (agent_config or {}).get("opensearch_config", {}),
            "ai": (agent_config or {}).get("ai_config", {}),
        }
        from src.splunk import execute_splunk_tool
        return execute_splunk_tool(splunk_cfg, tool_name, args)

    # --- Certificate inspection tools ---
    if tool_name in ("cert_find", "cert_list", "cert_details"):
        from src.certs import execute_certs_tool
        return execute_certs_tool(str(repo_root), tool_name, args)

    return f"Unknown tool: {tool_name}"


# ===================================================================
# Plan-mode tool dispatcher
# ===================================================================

_BLOCKED_IN_PLAN = {"write_file", "edit_file", "delete_file", "run_command"}


def execute_plan_tool(
    repo_root: Path,
    tool_name: str,
    args: dict,
    change_plan: "ChangePlan",
    working_memory: Optional[WorkingMemory] = None,
    gcc_controller: Optional["GCCController"] = None,
    code_index: Optional["CodeIndex"] = None,
) -> str:
    """Execute a tool in plan mode.

    - propose_change: validates and adds to the ChangePlan
    - read/memory/completion/gcc tools: delegated to execute_tool
    - write/exec tools: blocked with a helpful message
    """
    from src.agent.plan import ChangePlan, ChangeAction, ProposedChange

    repo = Path(repo_root)

    # --- Block write/exec tools ---
    if tool_name in _BLOCKED_IN_PLAN:
        return (
            f"Error: {tool_name} is not available in plan mode. "
            "Use propose_change to propose modifications instead."
        )

    # --- propose_change ---
    if tool_name == "propose_change":
        path = args.get("path", "").strip()
        action_str = args.get("action", "").strip().lower()
        description = args.get("description", "")
        content = args.get("content")
        old_string = args.get("old_string")
        new_string = args.get("new_string")

        if not path:
            return "Error: path is required"
        if action_str not in ("create", "modify", "delete"):
            return f"Error: action must be create, modify, or delete (got '{action_str}')"

        action = ChangeAction(action_str)

        if action == ChangeAction.create:
            if content is None:
                return "Error: content is required for create action"
            change = ProposedChange(
                path=path, action=action, description=description,
                new_content=content,
            )
            change_plan.add_change(change)
            return f"Proposed: CREATE {path} ({len(content)} chars)"

        elif action == ChangeAction.delete:
            # Verify file exists
            target = _safe_path(repo, path)
            if not target or not target.exists():
                return f"Error: File not found: {path}"
            change = ProposedChange(path=path, action=action, description=description)
            change_plan.add_change(change)
            return f"Proposed: DELETE {path}"

        elif action == ChangeAction.modify:
            # Verify file exists
            target = _safe_path(repo, path)
            if not target or not target.exists():
                return f"Error: File not found: {path}"

            if content is not None:
                # Full replacement
                change = ProposedChange(
                    path=path, action=action, description=description,
                    new_content=content,
                )
                change_plan.add_change(change)
                return f"Proposed: MODIFY {path} (full replacement, {len(content)} chars)"

            if old_string:
                # Surgical edit — validate old_string exists exactly once
                try:
                    file_content = target.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    return f"Error reading file: {e}"

                count = file_content.count(old_string)
                if count == 0:
                    return (
                        f"Error: old_string not found in {path}. "
                        "Make sure it matches exactly (including whitespace and indentation)."
                    )
                if count > 1:
                    return (
                        f"Error: old_string found {count} times in {path}. "
                        "Include more surrounding context lines to make it unique."
                    )

                change = ProposedChange(
                    path=path, action=action, description=description,
                    edits=[{"old_string": old_string, "new_string": new_string or ""}],
                )
                change_plan.add_change(change)
                return f"Proposed: MODIFY {path} (surgical edit, {len(old_string)} -> {len(new_string or '')} chars)"

            return "Error: modify action requires either content (full replacement) or old_string+new_string (surgical edit)"

    # --- Delegate read/memory/completion/gcc/code_index tools to existing dispatcher ---
    return execute_tool(repo, tool_name, args, working_memory=working_memory, gcc_controller=gcc_controller, code_index=code_index)


# ===================================================================
# Ask-mode tool dispatcher
# ===================================================================

_BLOCKED_IN_ASK = {"write_file", "edit_file", "delete_file", "run_command", "propose_change", "gcc_branch", "gcc_merge"}


def execute_ask_tool(
    repo_root: Path,
    tool_name: str,
    args: dict,
    working_memory: Optional[WorkingMemory] = None,
    gcc_controller: Optional["GCCController"] = None,
    code_index: Optional["CodeIndex"] = None,
) -> str:
    """Execute a tool in ask mode (read-only, no writes/exec/propose)."""
    if tool_name in _BLOCKED_IN_ASK:
        return f"Error: {tool_name} is not available in ask mode. Use read tools to explore the codebase."
    return execute_tool(repo_root, tool_name, args, working_memory=working_memory, gcc_controller=gcc_controller, code_index=code_index)
