"""
Post-edit verification gate.

Runs a series of checks on changed files before allowing a commit:
1. Syntax check (py_compile)
2. Import check (verify imports still resolve)
3. Scoped tests (find and run matching test files)
4. Caller check (verify changed signatures don't break callers)
"""

import ast
import logging
import os
import py_compile
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.code_index.storage import CodeIndex

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of the post-edit verification gate."""

    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repair_suggestions: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_repair_suggestion(self, msg: str) -> None:
        self.repair_suggestions.append(msg)

    def repair_prompt(self) -> str:
        """Generate a structured prompt for the retry agent."""
        if self.passed:
            return ""
        parts = ["## Verification failed — repair instructions"]
        if self.errors:
            parts.append("\n### Errors to fix")
            for e in self.errors:
                parts.append(f"  - {e}")
        if self.warnings:
            parts.append("\n### Warnings to address")
            for w in self.warnings:
                parts.append(f"  - {w}")
        if self.repair_suggestions:
            parts.append("\n### Suggested repairs")
            for s in self.repair_suggestions:
                parts.append(f"  - {s}")
        parts.append(
            "\nFix these issues. Run tests after making changes. "
            "Call task_complete when done."
        )
        return "\n".join(parts)

    def summary(self) -> str:
        parts = []
        if self.passed:
            parts.append("Verification PASSED")
        else:
            parts.append("Verification FAILED")
        if self.errors:
            parts.append(f"  Errors ({len(self.errors)}):")
            for e in self.errors:
                parts.append(f"    - {e}")
        if self.warnings:
            parts.append(f"  Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                parts.append(f"    - {w}")
        return "\n".join(parts)


def post_edit_verification_gate(
    repo_path: str,
    changed_files: list[str],
    code_index: CodeIndex,
    config: dict,
) -> VerificationResult:
    """Run all verification checks on changed files.

    Returns a VerificationResult indicating pass/fail with details.
    """
    result = VerificationResult()
    repo = Path(repo_path)

    py_files = [f for f in changed_files if f.endswith(".py")]
    java_files = [f for f in changed_files if f.endswith(".java")]

    if not py_files and not java_files:
        return result

    # Step 1: Syntax check
    _check_syntax(repo, py_files, result)
    _check_java_syntax(repo, java_files, result)

    # Step 2: Import check
    _check_imports(repo, py_files, result)

    # Step 3: Scoped tests
    _run_scoped_tests(repo, py_files + java_files, config, result)

    # Step 4: Caller check (warning-level)
    _check_callers(repo, py_files, code_index, result)

    # Step 5: Generate repair suggestions if verification failed
    if not result.passed:
        generate_repair_suggestions(result, code_index, changed_files)

    return result


def _check_syntax(repo: Path, files: list[str], result: VerificationResult) -> None:
    """Verify each changed .py file compiles without syntax errors."""
    for rel_path in files:
        fpath = repo / rel_path
        if not fpath.exists():
            continue
        try:
            py_compile.compile(str(fpath), doraise=True)
        except py_compile.PyCompileError as exc:
            result.add_error(f"Syntax error in {rel_path}: {exc}")


def _check_java_syntax(repo: Path, files: list[str], result: VerificationResult) -> None:
    """Verify each changed .java file parses without errors using javalang."""
    try:
        import javalang
    except ImportError:
        return  # javalang not installed, skip check

    for rel_path in files:
        fpath = repo / rel_path
        if not fpath.exists():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            javalang.parse.parse(content)
        except javalang.parser.JavaSyntaxError as exc:
            result.add_error(f"Java syntax error in {rel_path}: {exc}")
        except Exception as exc:
            result.add_error(f"Java parse error in {rel_path}: {exc}")


def _check_imports(repo: Path, files: list[str], result: VerificationResult) -> None:
    """Verify all imports in changed files can be resolved."""
    for rel_path in files:
        fpath = repo / rel_path
        if not fpath.exists():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in tree.body:  # imports are module-level; skip full AST walk
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = node.level or 0
                if level > 0:
                    continue  # Skip relative imports (harder to validate statically)
                # Check if module path maps to an existing file
                parts = module.split(".")
                candidate = "/".join(parts) + ".py"
                candidate_init = "/".join(parts) + "/__init__.py"
                if not (repo / candidate).exists() and not (repo / candidate_init).exists():
                    # Could be stdlib/third-party — only warn if it looks like an in-repo path
                    if parts and parts[0] in ("src",):
                        result.add_warning(
                            f"Import may not resolve in {rel_path}: from {module} import ..."
                        )


def _run_scoped_tests(
    repo: Path, files: list[str], config: dict, result: VerificationResult
) -> None:
    """Find and run test files matching changed modules."""
    test_files: list[str] = []
    for rel_path in files:
        module_name = Path(rel_path).stem
        # Look for test_<module>.py or <module>_test.py anywhere in tests/
        for test_dir in ["tests", "test"]:
            test_path = repo / test_dir
            if not test_path.is_dir():
                continue
            for candidate in [f"test_{module_name}.py", f"{module_name}_test.py"]:
                full = test_path / candidate
                if full.exists():
                    test_files.append(str(full.relative_to(repo)))

    if not test_files:
        return

    # Run pytest on matched test files
    test_timeout = config.get("testing", {}).get("test_timeout", 120)
    try:
        cmd = ["python", "-m", "pytest", "-x", "-q"] + test_files
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=test_timeout,
        )
        if proc.returncode != 0:
            output = (proc.stdout + "\n" + proc.stderr).strip()
            result.add_error(
                f"Scoped tests failed ({', '.join(test_files)}): {output[:500]}"
            )
    except subprocess.TimeoutExpired:
        result.add_error(f"Scoped tests timed out after {test_timeout}s")
    except FileNotFoundError:
        result.add_warning("pytest not found; skipping scoped tests")


def _check_callers(
    repo: Path, files: list[str], code_index: CodeIndex, result: VerificationResult
) -> None:
    """Warn if changed function signatures might break callers.

    For each function/method in the changed files, re-extract its signature
    from the current file on disk and compare against the indexed version.
    If the parameter list changed and there are callers, issue a warning.
    """
    from src.code_index.symbol_table import extract_symbols_from_source

    for rel_path in files:
        fpath = repo / rel_path
        if not fpath.exists():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        current_symbols = extract_symbols_from_source(rel_path, content)
        current_by_fqn = {s.fqn: s for s in current_symbols}

        indexed_symbols = code_index.symbol_table.get_by_file(rel_path)
        for indexed in indexed_symbols:
            if indexed.symbol_type in ("function", "method", "async function"):
                current = current_by_fqn.get(indexed.fqn)
                if current is None:
                    # Symbol was removed — check for callers
                    callers = code_index.dependency_graph.get_callers(indexed.fqn)
                    if callers:
                        result.add_warning(
                            f"Removed {indexed.fqn} has {len(callers)} caller(s)"
                        )
                elif current.params != indexed.params:
                    # Signature changed — check for callers
                    callers = code_index.dependency_graph.get_callers(indexed.fqn)
                    if callers:
                        result.add_warning(
                            f"Changed signature of {indexed.fqn} — "
                            f"{len(callers)} caller(s) may need updating"
                        )


def generate_repair_suggestions(
    result: VerificationResult,
    code_index: CodeIndex,
    changed_files: list[str],
) -> None:
    """Enrich a VerificationResult with graph-aware repair suggestions.

    Called automatically from ``post_edit_verification_gate`` when
    verification fails.  Produces actionable repair instructions that
    a retry agent can follow.
    """
    for error in result.errors:
        # Syntax errors
        if "Syntax error" in error or "syntax error" in error.lower():
            # Extract file from "Syntax error in <file>: ..."
            parts = error.split(":")
            if len(parts) >= 2:
                file_ref = parts[0].replace("Syntax error in ", "").strip()
                result.add_repair_suggestion(f"Fix syntax in {file_ref}")

        # Test failures
        if "tests failed" in error.lower() or "test" in error.lower():
            # Find test files for changed modules
            for f in changed_files:
                if not f.endswith(".py"):
                    continue
                module_name = f.split("/")[-1].replace(".py", "")
                test_patterns = {f"test_{module_name}.py", f"{module_name}_test.py"}
                related_tests = [
                    tf for tf in code_index.symbol_table.all_files
                    if tf.split("/")[-1] in test_patterns
                ]
                for tf in related_tests:
                    result.add_repair_suggestion(
                        f"Read {tf} to understand failing assertions"
                    )

    for warning in result.warnings:
        # Signature change warnings — list actual caller locations
        if "caller(s) may need updating" in warning or "caller(s)" in warning:
            # Extract FQN from warning: "Changed signature of <fqn> — N caller(s)..."
            fqn = None
            if "Changed signature of " in warning:
                fqn = warning.split("Changed signature of ")[1].split(" —")[0].strip()
            elif "Removed " in warning:
                fqn = warning.split("Removed ")[1].split(" has")[0].strip()

            if fqn:
                callers = code_index.dependency_graph.get_callers(fqn)
                for caller_fqn in sorted(callers):
                    caller_entry = code_index.symbol_table.get_by_fqn(caller_fqn)
                    if caller_entry:
                        result.add_repair_suggestion(
                            f"Update caller {caller_fqn} at {caller_entry.file_path}:{caller_entry.line_start}"
                        )
                    else:
                        result.add_repair_suggestion(f"Update caller {caller_fqn}")

        # Import warnings
        if "Import may not resolve" in warning or "import" in warning.lower():
            # Extract file from warning
            if " in " in warning:
                file_ref = warning.split(" in ")[1].split(":")[0].strip()
                result.add_repair_suggestion(f"Check imports in {file_ref}")
