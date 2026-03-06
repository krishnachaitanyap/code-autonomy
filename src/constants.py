"""
Shared constants for code discovery and filtering.
"""

# File extensions for code files
CODE_EXTENSIONS = {".py", ".java", ".kt", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".swift"}

# Extensions for search/grep (code + config/resource files)
SEARCH_EXTENSIONS = {
    # Code
    ".py", ".java", ".kt", ".js", ".ts", ".tsx", ".jsx",
    # Config / resources
    ".properties", ".yml", ".yaml", ".xml", ".json", ".toml", ".ini",
    ".cfg", ".conf", ".env",
    # Data / schema
    ".sql", ".graphql", ".proto",
    # Docs / web
    ".md", ".txt", ".html", ".css", ".scss",
}

# Directories to skip when walking repos
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".gradle", ".mvn", ".idea",
}
