#!/usr/bin/env python3
"""
Grep-style search across repository (Python/Java).
Usage: python run_grep.py <repo_path> <pattern> [--file *.py] [--context 2]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.code_search import grep, format_grep_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Search code (grep-like)")
    parser.add_argument("repo_path", help="Path to repository")
    parser.add_argument("pattern", help="Search pattern (regex)")
    parser.add_argument("--file", "-f", help="File pattern filter (e.g., *.py)")
    parser.add_argument("--context", "-C", type=int, default=2, help="Context lines")
    parser.add_argument("--max", "-n", type=int, default=500, help="Max results")
    args = parser.parse_args()

    results = grep(
        args.repo_path,
        args.pattern,
        file_pattern=args.file,
        context_lines=args.context,
        max_results=args.max,
    )
    print(format_grep_results(results))
    print(f"\n({len(results)} matches)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
