"""
Smart context management for the agent loop.

Provides:
- Token counting per LLM provider (model-aware context limits)
- Intelligent summarization of large tool outputs via fast LLM calls
- Conversation context compression when approaching limits
- Requirement-aware initial context building
"""

import re
from typing import Optional

from src.consciousness.core import ProjectConsciousness, _format_structure


# ---------------------------------------------------------------------------
# 1. Token counting (per provider)
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-3-5-haiku": 200_000,
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
}

_DEFAULT_CONTEXT_LIMIT = 100_000  # safe fallback


def estimate_tokens(text: str) -> int:
    """Estimate token count (~3.5 chars per token for English/code)."""
    return int(len(text) / 3.5)


def get_context_limit(model: str, margin: float = 0.80) -> int:
    """Return usable context window for *model* (with safety margin)."""
    model_lower = model.lower()
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return int(limit * margin)
    return int(_DEFAULT_CONTEXT_LIMIT * margin)


def get_messages_token_count(messages: list[dict]) -> int:
    """Estimate total tokens across all messages."""
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.get("content", "") or "")
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("arguments", "") or "")
            total += estimate_tokens(fn.get("name", "") or "")
    return total


# ---------------------------------------------------------------------------
# 2. Intelligent summarization
# ---------------------------------------------------------------------------

_SUMMARIZE_THRESHOLD = 15_000  # chars — only summarize above this


def _get_summary_model_config(llm_config: dict) -> dict:
    """Return a fast/cheap model config from the same provider."""
    provider = (llm_config.get("provider") or "openai").lower()
    summary_models = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "gemini": "gemini-1.5-flash",
        "google": "gemini-1.5-flash",
    }
    config = dict(llm_config)
    config["model"] = summary_models.get(provider, llm_config.get("model", "gpt-4o-mini"))
    return config


def summarize_large_output(
    content: str,
    tool_name: str,
    llm_config: dict,
    full_config: Optional[dict] = None,
    usage_stats: "Optional[LLMUsageStats]" = None,
    summarization_budget: int = 0,
) -> str:
    """Summarize a large tool result using a fast LLM call.

    Only invoked when *content* exceeds ``_SUMMARIZE_THRESHOLD``.
    Preserves error messages, file paths, test counts, and actionable info.

    If *usage_stats* is provided, the summarization LLM call's token usage
    is recorded so it doesn't become a hidden cost.

    If *summarization_budget* > 0 and the budget is exhausted, falls back
    to plain truncation instead of making another LLM call.
    """
    if len(content) < _SUMMARIZE_THRESHOLD:
        return content

    # Budget check: fall back to truncation when budget is exhausted
    if summarization_budget > 0 and usage_stats:
        if usage_stats.calls_by_category("summarization") >= summarization_budget:
            return content[:_SUMMARIZE_THRESHOLD] + "\n...(summarization budget exhausted)"

    summary_config = _get_summary_model_config(llm_config)

    prompt = (
        f"Summarize this {tool_name} output concisely. Preserve:\n"
        "- All error messages, tracebacks, and failure reasons\n"
        "- File paths and line numbers\n"
        "- Key function/class names\n"
        "- Test results (pass/fail counts)\n"
        "- Any actionable information\n\n"
        f"Output:\n{content[:30_000]}"
    )

    try:
        from src.llm_client import chat_completion

        summary, _ = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            config=summary_config,
            temperature=0.0,
            full_config=full_config,
            usage_stats=usage_stats,
            usage_category="summarization",
        )
        return f"[Summarized from {len(content)} chars]\n{summary}"
    except Exception:
        # Fallback: plain truncation if summarization fails
        return content[:_SUMMARIZE_THRESHOLD] + f"\n...(truncated, {len(content)} total chars)"


# ---------------------------------------------------------------------------
# 3. Conversation context compression
# ---------------------------------------------------------------------------

_PROTECTED_HEAD = 2   # system + initial user message
_PROTECTED_TAIL = 8   # most recent messages


def manage_conversation_context(
    messages: list[dict],
    model: str,
    llm_config: dict,
    smart_summarization: bool = True,
    full_config: Optional[dict] = None,
    usage_stats: "Optional[LLMUsageStats]" = None,
    summarization_budget: int = 0,
) -> list[dict]:
    """Compress conversation when approaching context limits.

    Strategy:
    1. Keep system prompt + initial user message + last 12 messages intact.
    2. Middle messages: summarize large tool results (>2 KB).
    3. If still too large: drop oldest middle messages in pairs.

    If *usage_stats* is provided, any summarization LLM calls are tracked.
    If *summarization_budget* > 0, summarization LLM calls are capped.
    """
    context_limit = get_context_limit(model)
    current_tokens = get_messages_token_count(messages)

    if current_tokens < int(context_limit * 0.70):
        return messages  # plenty of room

    if len(messages) <= _PROTECTED_HEAD + _PROTECTED_TAIL:
        return messages  # nothing safe to compress

    head = messages[:_PROTECTED_HEAD]
    middle = list(messages[_PROTECTED_HEAD:-_PROTECTED_TAIL])
    tail = messages[-_PROTECTED_TAIL:]

    # Phase 1: compress large tool results in the middle
    compressed_middle: list[dict] = []
    for msg in middle:
        # Skip messages that were already summarized in a prior compression pass
        if msg.get("_summarized"):
            compressed_middle.append(msg)
            continue
        content = msg.get("content", "") or ""
        if msg.get("role") == "tool" and len(content) > 2000:
            if smart_summarization:
                summarized = summarize_large_output(
                    content, "tool_result", llm_config,
                    full_config=full_config, usage_stats=usage_stats,
                    summarization_budget=summarization_budget,
                )
            else:
                summarized = content[:500] + f"\n...(compressed, was {len(content)} chars)"
            compressed_middle.append({**msg, "content": summarized, "_summarized": True})
        else:
            compressed_middle.append(msg)

    result = head + compressed_middle + tail

    # Phase 2: drop oldest middle messages if still too large
    while (
        get_messages_token_count(result) > int(context_limit * 0.80)
        and len(result) > _PROTECTED_HEAD + _PROTECTED_TAIL + 2
    ):
        result = result[:_PROTECTED_HEAD] + result[_PROTECTED_HEAD + 2:]

    return result


# ---------------------------------------------------------------------------
# 4. Requirement-aware initial context
# ---------------------------------------------------------------------------

def build_smart_initial_context(
    repo_path: str,
    requirements: str,
    consciousness: Optional[ProjectConsciousness] = None,
) -> str:
    """Build focused initial context derived from *requirements*.

    Instead of dumping 25 KB of random code samples, this function:
    1. Extracts identifiers (CamelCase / snake_case) from requirements.
    2. Finds files that contain those identifiers.
    3. Lists matching class/function signatures from consciousness.
    4. Provides a compact project overview (language, build, structure).
    """
    from src.context.enrichers.grep_enricher import (
        _extract_identifiers,
        _parse_grep_from_requirements,
    )
    from src.code.search import grep_files

    identifiers = _extract_identifiers(requirements)
    explicit_patterns = _parse_grep_from_requirements(requirements)
    all_patterns = explicit_patterns + identifiers

    # Find files containing these identifiers
    relevant_files: set[str] = set()
    for pattern in all_patterns[:10]:
        try:
            found = grep_files(repo_path, pattern)
            relevant_files.update(found[:5])
        except Exception:
            pass

    # File paths explicitly mentioned in the requirements text
    for m in re.finditer(r"[\w/]+\.(?:py|java|kt|js|ts|tsx|jsx|go|rb|rs)", requirements):
        relevant_files.add(m.group(0))

    lines: list[str] = []

    # Project overview
    if consciousness:
        conv = consciousness.conventions
        lines.append("## Project Overview")
        lines.append(f"Language: {conv.get('language', 'unknown')}")
        lines.append(f"Build: {conv.get('build_tool', 'unknown')}")
        lines.append(f"Tests: {conv.get('test_framework', 'unknown')}")
        lines.append(f"Style: {conv.get('naming_style', 'unknown')}")
        lines.append("")
        lines.append("## Project Structure")
        lines.append(_format_structure(consciousness.structure))

    # Build metadata (pre-parsed from pom.xml, package.json, etc.)
    try:
        from src.agent.direct_lookup import parse_structured_file
        _build_files = ["pom.xml", "package.json", "build.gradle", "pyproject.toml", "Cargo.toml"]
        for bf in _build_files:
            bf_path = Path(repo_path) / bf
            if bf_path.is_file():
                parsed = parse_structured_file(str(bf_path))
                if parsed:
                    important = {
                        k: v for k, v in parsed.items()
                        if any(t in k.lower() for t in [
                            "name", "version", "group", "artifact", "description",
                            "packaging", "java.version",
                        ])
                    }
                    if important:
                        lines.append("")
                        lines.append(f"## Build Metadata ({bf})")
                        for k, v in list(important.items())[:8]:
                            lines.append(f"  {k}: {v}")
                break  # Only include first found build file
    except Exception:
        pass

    # Relevant files
    if relevant_files:
        lines.append("")
        lines.append(f"## Files likely relevant to requirements ({len(relevant_files)} found)")
        for f in sorted(relevant_files)[:15]:
            lines.append(f"  - {f}")

    # Matching signatures
    if consciousness and consciousness.signatures and all_patterns:
        matching_sigs = [
            sig
            for sig in consciousness.signatures
            if any(p.lower() in sig.get("name", "").lower() for p in all_patterns)
        ]
        if matching_sigs:
            lines.append("")
            lines.append("## Relevant classes/functions")
            for sig in matching_sigs[:20]:
                lines.append(f"  {sig['path']}: {sig['type']} {sig['name']}")

    return "\n".join(lines) if lines else ""
