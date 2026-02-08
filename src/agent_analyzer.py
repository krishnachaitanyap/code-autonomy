"""
Agent-based code analysis with tool use.
AI iteratively calls read_file, grep, list_dir to build context before generating changes.
"""

import json
from pathlib import Path
from typing import Optional

from src.agent_tools import AGENT_TOOLS, execute_tool
from src.ai_utils import parse_ai_changes


def generate_changes_with_agent(
    requirements: str,
    repo_path: str,
    api_key: str,
    model: str = "gpt-4o",
    reference_pr_content: str = "",
    max_turns: int = 15,
    verbose: bool = False,
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    consciousness_context: str = "",
) -> list[dict]:
    """
    Run agent loop: AI uses read_file, grep, list_dir, find_files to explore codebase,
    then produces JSON changes when ready.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    repo_root = Path(repo_path)

    system_prompt = """You are an expert software engineer. You have tools to explore the codebase:
- read_file(path, start_line?, end_line?): Read file contents
- grep(pattern, path_filter?, context_lines?): Search for pattern
- list_dir(path): List directory contents (use "" for repo root)
- find_files(extension?, pattern?): Find files by extension or glob

Your task: Implement the requirements. First EXPLORE the codebase using tools to understand structure, conventions, and where to add changes. Then when you have enough context, output the changes.

When ready to submit, respond with ONLY valid JSON (no tool calls):
{"changes": [{"path": "relative/path", "content": "full file content", "action": "create"|"modify"}, ...]}

Rules:
- Use tools to read relevant files before generating changes
- Adapt paths and packages to match the current codebase (use project context when provided)
- For "modify": provide COMPLETE file content
- Output only the JSON when done, no explanation
- When generating Java tests, follow the testing strategy guidance when provided (BDD, Contract, Integration, Unit, E2E, SOAP)"""

    from src.testing_strategies import get_testing_strategy_context
    from src.code_executor import detect_build_tool
    bt = build_tool or detect_build_tool(str(repo_root))
    testing_ctx = get_testing_strategy_context(testing_strategy, bt, requirements)
    testing_section = f"\n## Testing strategy (for Java tests)\n{testing_ctx}\n" if testing_ctx else ""

    consciousness_section = f"\n{consciousness_context}\n" if consciousness_context else ""
    ref_section = f"\n\nReference PR (use as template):\n{reference_pr_content}" if reference_pr_content else ""
    user_msg = f"""## Requirements
{requirements}
{consciousness_section}
{testing_section}
{ref_section}

Explore the codebase with the tools, then produce the JSON changes. Start by listing the repo root with list_dir."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    for turn in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        choice = response.choices[0]
        msg = choice.message

        if not getattr(msg, "tool_calls", None) or len(msg.tool_calls) == 0:
            # No tool calls - AI is done, parse changes from content
            content = (msg.content or "").strip()
            if verbose:
                print(f"  Agent turn {turn + 1}: final response ({len(content)} chars)")
            return parse_ai_changes(content)

        # Execute tool calls - append assistant message with all tool_calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(repo_root, name, args)
            if verbose:
                print(f"  Agent turn {turn + 1}: {name}({list(args.keys())}) -> {len(result)} chars")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result[:12000] + "\n...(truncated)" if len(result) > 12000 else result,
            })

    return []
