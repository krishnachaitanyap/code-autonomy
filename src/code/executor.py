"""
Run code and tests in isolation for Python and Java.
Execute, capture output, verify results.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def _run(
    cmd: list[str],
    cwd: str,
    timeout: int = 120,
    env: Optional[dict] = None,
) -> tuple[int, str, str]:
    """Run command, return (exit_code, stdout, stderr)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError as e:
        return -1, "", str(e)
    except Exception as e:
        return -1, "", str(e)


def detect_build_tool(repo_path: str) -> Optional[str]:
    """Detect Maven or Gradle from repo. Returns 'maven', 'gradle', or None."""
    repo = Path(repo_path)
    if (repo / "pom.xml").exists():
        return "maven"
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        return "gradle"
    return None


def detect_project_type(repo_path: str) -> str:
    """Detect project type: python, java_maven, java_gradle, or unknown."""
    repo = Path(repo_path)
    if (repo / "pom.xml").exists():
        return "java_maven"
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        return "java_gradle"
    if (repo / "pytest.ini").exists() or (repo / "pyproject.toml").exists():
        return "python"
    if any(repo.rglob("test_*.py")) or any(repo.rglob("*_test.py")):
        return "python"
    if any(repo.rglob("*Test*.java")) or any(repo.rglob("*Tests.java")):
        return "java_maven"  # assume maven if pom exists
    # Default: check for any Python/Java
    if any(repo.rglob("*.py")):
        return "python"
    if any(repo.rglob("*.java")):
        return "java_maven"
    return "unknown"


def run_python_tests(repo_path: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run pytest or unittest. Returns (exit_code, stdout, stderr)."""
    repo = Path(repo_path)
    # Prefer pytest
    pytest_bin = "pytest"
    if (repo / "venv").exists() or (repo / ".venv").exists():
        venv = repo / "venv" if (repo / "venv").exists() else repo / ".venv"
        pytest_bin = str(venv / "bin" / "pytest")

    # Try pytest first
    code, out, err = _run(
        [pytest_bin, "-v", "--tb=short", "-x"],
        cwd=repo_path,
        timeout=timeout,
    )
    if code != -1 or "not found" not in err.lower():
        return code, out, err

    # Fallback to python -m pytest
    code, out, err = _run(
        ["python", "-m", "pytest", "-v", "--tb=short", "-x"],
        cwd=repo_path,
        timeout=timeout,
    )
    if code != -1:
        return code, out, err

    # Fallback to python -m unittest
    return _run(
        ["python", "-m", "unittest", "discover", "-v"],
        cwd=repo_path,
        timeout=timeout,
    )


def run_java_tests(repo_path: str, timeout: int = 180) -> tuple[int, str, str]:
    """Run Maven or Gradle tests. Returns (exit_code, stdout, stderr)."""
    repo = Path(repo_path)
    if (repo / "pom.xml").exists():
        return _run(
            ["mvn", "test", "-B"],
            cwd=repo_path,
            timeout=timeout,
        )
    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        return _run(
            ["./gradlew", "test", "--no-daemon"],
            cwd=repo_path,
            timeout=timeout,
        )
    return -1, "", "No Maven or Gradle project found"


def run_tests(repo_path: str, project_type: Optional[str] = None, timeout: int = 120) -> tuple[int, str, str]:
    """
    Run tests based on project type.
    Returns (exit_code, stdout, stderr). Exit 0 = success.
    """
    ptype = project_type or detect_project_type(repo_path)
    if ptype == "python":
        return run_python_tests(repo_path, timeout)
    if ptype in ("java_maven", "java_gradle"):
        return run_java_tests(repo_path, timeout)
    # Try both
    code, out, err = run_python_tests(repo_path, timeout)
    if code != -1:
        return code, out, err
    return run_java_tests(repo_path, timeout)


def run_python_script(
    script_path: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
    stdin: Optional[str] = None,
) -> tuple[int, str, str]:
    """Run a Python script in isolation. Returns (exit_code, stdout, stderr)."""
    cwd = cwd or str(Path(script_path).parent)
    cmd = ["python", script_path]
    env = None
    if stdin:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    return _run(cmd, cwd=cwd, timeout=timeout)


def run_java_main(
    repo_path: str,
    main_class: Optional[str] = None,
    timeout: int = 60,
) -> tuple[int, str, str]:
    """Compile and run Java main class. Returns (exit_code, stdout, stderr)."""
    repo = Path(repo_path)
    if (repo / "pom.xml").exists():
        # mvn exec:java -Dexec.mainClass=...
        cmd = ["mvn", "exec:java", "-q", "-Dexec.mainClass=" + (main_class or "Main")]
        return _run(cmd, cwd=repo_path, timeout=timeout)
    # Gradle: run main if configured
    if (repo / "build.gradle").exists():
        return _run(["./gradlew", "run", "--no-daemon", "-q"], cwd=repo_path, timeout=timeout)
    return -1, "", "Java project not configured for direct run"


def verify_output(actual: str, expected: str, exact: bool = False) -> bool:
    """Verify output matches expected. If exact=False, expected is substring."""
    if exact:
        return actual.strip() == expected.strip()
    return expected.strip() in actual
