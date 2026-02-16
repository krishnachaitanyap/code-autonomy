"""
CodeIndex — Precision Code Intelligence for Background Agent.

Public API:
    CodeIndex               — composite dataclass holding all index data
    build_code_index        — build fresh index from repo on disk
    build_or_load_code_index— build or load from cache
    CODE_INDEX_TOOLS        — list of tool schemas for the agent
    execute_code_index_tool — dispatcher for code index tools
    post_edit_verification_gate — post-edit verification gate
"""

from src.code_index.storage import CodeIndex, build_code_index, build_or_load_code_index
from src.code_index.tools import CODE_INDEX_TOOLS, CODE_INDEX_TOOL_NAMES, execute_code_index_tool
from src.code_index.verifier import post_edit_verification_gate, VerificationResult, generate_repair_suggestions

__all__ = [
    "CodeIndex",
    "build_code_index",
    "build_or_load_code_index",
    "CODE_INDEX_TOOLS",
    "CODE_INDEX_TOOL_NAMES",
    "execute_code_index_tool",
    "post_edit_verification_gate",
    "VerificationResult",
    "generate_repair_suggestions",
]
