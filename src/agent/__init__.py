"""Agent loop infrastructure."""
# Lazy re-exports to avoid circular imports at package init time.
# Direct imports from submodules (e.g., from src.agent.analyzer import X) always work.


def __getattr__(name):
    # Lazily resolve public names on first access
    import importlib

    _MODULE_MAP = {
        "AgentResult": "src.agent.analyzer",
        "generate_changes_with_agent": "src.agent.analyzer",
        "build_agent_tools": "src.agent.tools",
        "execute_tool": "src.agent.tools",
        "AGENT_TOOLS": "src.agent.tools",
        "WorkingMemory": "src.agent.knowledge",
        "KnowledgeEntry": "src.agent.knowledge",
        "compute_repo_id": "src.agent.knowledge",
        "load_knowledge": "src.agent.knowledge",
        "save_knowledge": "src.agent.knowledge",
        "build_smart_initial_context": "src.agent.context",
        "manage_conversation_context": "src.agent.context",
        "summarize_large_output": "src.agent.context",
        "step": "src.agent.activity",
        "spinner": "src.agent.activity",
        "header": "src.agent.activity",
        "log_info": "src.agent.activity",
        "log_success": "src.agent.activity",
        "log_error": "src.agent.activity",
        "log_warning": "src.agent.activity",
        "parse_ai_changes": "src.agent.ai_utils",
    }

    if name in _MODULE_MAP:
        mod = importlib.import_module(_MODULE_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
