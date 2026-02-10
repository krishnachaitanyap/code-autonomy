"""Code analysis, search, and execution."""
from src.code.analyzer import load_codebase_context, generate_changes, apply_changes
from src.code.search import grep, grep_files, format_grep_results, search_codebase
from src.code.executor import run_tests, detect_project_type, detect_build_tool
from src.code.testing_strategies import get_testing_strategy_context
