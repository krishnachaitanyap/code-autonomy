"""
AI-powered code analysis and generation.
Uses LLM (OpenAI, Anthropic, Gemini via LiteLLM) to understand requirements and generate code changes.
Supports Python and Java with error analysis and regeneration.
"""

import json
from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS


def load_codebase_context(repo_path: str, max_files: int = 30, max_chars_per_file: int = 4000) -> str:
    """Load relevant files from the codebase for context."""
    repo = Path(repo_path)
    if not repo.exists():
        return ""

    files_content: list[tuple[str, str]] = []
    total_chars = 0

    for f in repo.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in CODE_EXTENSIONS:
            continue
        # Skip common non-source dirs
        parts = f.relative_to(repo).parts
        if any(p in SKIP_DIRS for p in parts):
            continue

        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        trunc = content[:max_chars_per_file]
        if len(content) > max_chars_per_file:
            trunc += "\n... (truncated)"

        rel_path = str(f.relative_to(repo))
        files_content.append((rel_path, trunc))
        total_chars += len(trunc)

        if len(files_content) >= max_files or total_chars > 80000:
            break

    if not files_content:
        return "No code files found in repository."

    lines = []
    for path, content in sorted(files_content, key=lambda x: x[0]):
        lines.append(f"--- {path} ---\n{content}\n")
    return "\n".join(lines)


def generate_changes(
    requirements: str,
    codebase_context: str,
    llm_config: dict,
    verbose: bool = False,
    reference_pr_content: str = "",
    framework_context: str = "",
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    full_config: Optional[dict] = None,
) -> list[dict]:
    """
    Use AI to generate file changes based on requirements.
    Returns list of {"path": str, "content": str, "action": "create"|"modify"}.
    llm_config: provider, model, api_key, base_url, api_key_env from config.
    """

    system_prompt = """You are an expert software engineer. Your task is to analyze requirements and produce concrete code changes.
You support both Python and Java (and Kotlin). Follow the existing project's language and conventions.

Given:
1. A list of requirements (from changes.txt)
2. The current codebase context (relevant files)
3. Optionally: a reference PR (previous similar change) - use it as a template/pattern to follow

You MUST respond with a JSON array of file changes. Each change has:
- "path": relative file path (e.g., "src/utils.py")
- "content": full new file content (for modify) or content for new file (for create)
- "action": "create" or "modify"

Rules:
- Only output valid JSON. No markdown, no explanation outside the JSON.
- For "modify": provide the COMPLETE file content with your changes applied.
- For "create": provide the full content of the new file.
- Preserve existing code style, imports, and structure when modifying.
- If the requirement cannot be fulfilled with the given context, still provide your best attempt.
- Adapt to project structure and conventions (see project context when provided).
- When framework context is provided: it is REFERENCE ONLY. Do NOT modify framework code or propose changes to framework files. Only modify files in the application repo.
- Output format: {"changes": [{"path": "...", "content": "...", "action": "modify"|"create"}, ...]}"""

    from src.code.testing_strategies import get_testing_strategy_context

    testing_section = ""
    if testing_strategy and testing_strategy != "auto":
        ctx = get_testing_strategy_context(testing_strategy, build_tool, requirements)
        if ctx:
            testing_section = f"\n{ctx}\n"
    elif ".java" in codebase_context or "pom.xml" in codebase_context or "build.gradle" in codebase_context:
        # Java project: include auto-inferred strategy
        ctx = get_testing_strategy_context("auto", build_tool, requirements)
        if ctx:
            testing_section = f"\n{ctx}\n"

    reference_section = ""
    if reference_pr_content:
        reference_section = f"""
## Reference PR (use as template for similar changes)
{reference_pr_content}
"""
    framework_section = ""
    if framework_context:
        framework_section = f"""
{framework_context}
"""
    user_prompt = f"""## Requirements
{requirements}
{reference_section}
{framework_section}
{testing_section}
## Current Codebase
{codebase_context}

Produce the JSON array of file changes to implement the requirements (adapt paths and packages to match the current codebase)."""

    from src.llm_client import chat_completion

    content, _ = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        config=llm_config,
        temperature=float(llm_config.get("temperature", 0.2)),
        full_config=full_config,
    )
    if verbose:
        print("AI Response (raw):", content[:500], "...")

    from src.agent.ai_utils import parse_ai_changes
    return parse_ai_changes(content)


def apply_changes(repo_path: str, changes: list[dict]) -> list[str]:
    """Apply generated changes to the filesystem. Returns list of modified paths."""
    repo = Path(repo_path)
    modified = []

    for change in changes:
        path = change.get("path")
        content = change.get("content")
        action = change.get("action", "modify")

        if not path or content is None:
            continue

        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        modified.append(path)

    return modified


def regenerate_with_error_analysis(
    requirements: str,
    codebase_context: str,
    error_output: str,
    previous_changes: list[dict],
    llm_config: dict,
    verbose: bool = False,
    reference_pr_content: str = "",
    framework_context: str = "",
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    full_config: Optional[dict] = None,
) -> list[dict]:
    """
    Given test/execution failure, analyze error and regenerate fixes.
    Returns new list of changes.
    llm_config: provider, model, api_key, base_url, api_key_env from config.
    """

    system_prompt = """You are an expert software engineer. Tests or execution failed. Your task is to FIX the code based on the error output.

Given:
1. Original requirements
2. Current codebase context
3. Error output (test failure, traceback, compilation error, etc.)
4. Previous changes that were applied (which failed)

You MUST respond with a JSON array of file changes that FIX the errors. Each change has:
- "path": relative file path
- "content": full new file content (complete file, not a patch)
- "action": "create" or "modify"

Rules:
- Output ONLY valid JSON. No markdown, no explanation outside the JSON.
- For "modify": provide the COMPLETE corrected file content.
- Focus on fixing the specific errors shown in the error output.
- Preserve working parts of the code; only fix what's broken.
- When framework context is provided: it is REFERENCE ONLY. Do NOT modify framework code. Only modify files in the application repo.
- Output format: {"changes": [{"path": "...", "content": "...", "action": "modify"|"create"}, ...]}"""

    from src.code.testing_strategies import get_testing_strategy_context

    testing_section = ""
    if testing_strategy and ".java" in codebase_context:
        ctx = get_testing_strategy_context(testing_strategy, build_tool, requirements)
        if ctx:
            testing_section = f"\n## Testing strategy (follow when fixing tests)\n{ctx}\n"

    reference_section = f"\n## Reference PR (if relevant for style/conventions)\n{reference_pr_content}\n" if reference_pr_content else ""
    framework_section = f"\n{framework_context}\n" if framework_context else ""
    user_prompt = f"""## Original Requirements
{requirements}
{reference_section}
{framework_section}
{testing_section}
## Current Codebase (after previous changes)
{codebase_context}

## Error Output (tests/execution failed)
{error_output}

## Previous changes that were applied
{json.dumps(previous_changes, indent=2)[:2000]}

Produce the JSON array of file changes to FIX these errors."""

    from src.llm_client import chat_completion

    content, _ = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        config=llm_config,
        temperature=float(llm_config.get("temperature", 0.2)),
        full_config=full_config,
    )
    if verbose:
        print("AI regeneration response:", content[:300], "...")

    from src.agent.ai_utils import parse_ai_changes
    return parse_ai_changes(content)
