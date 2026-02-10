#!/usr/bin/env python3
"""
Run tests in isolation for a repository.
Usage: python run_tests.py <repo_path> [--timeout 120]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.code.executor import run_tests, detect_project_type


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tests for Python/Java project")
    parser.add_argument("repo_path", help="Path to repository")
    parser.add_argument("--timeout", "-t", type=int, default=120, help="Timeout in seconds")
    args = parser.parse_args()

    ptype = detect_project_type(args.repo_path)
    print(f"Detected: {ptype}")
    code, stdout, stderr = run_tests(args.repo_path, ptype, timeout=args.timeout)
    print("stdout:", stdout or "(empty)")
    if stderr:
        print("stderr:", stderr)
    print(f"Exit code: {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
