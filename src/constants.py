"""
Shared constants for code discovery and filtering.
"""

# File extensions for code files
CODE_EXTENSIONS = {".py", ".java", ".kt", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".swift"}

# Extensions for search/grep (subset - primary languages)
SEARCH_EXTENSIONS = {".py", ".java", ".kt", ".js", ".ts", ".tsx", ".jsx"}

# Directories to skip when walking repos
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".gradle", ".mvn", ".idea",
}
