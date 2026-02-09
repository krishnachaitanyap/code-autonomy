#!/usr/bin/env python3
"""
Verify modular context pipeline works for both legacy and pipeline modes.
Runs without cloning or AI calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.context import build_context
from src.context.enrichers import get_enabled_enrichers


def main() -> int:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config.ini"
    changes_path = project_root / "changes.txt"

    if not config_path.exists():
        print("ERROR: config.ini not found")
        return 1
    if not changes_path.exists():
        print("ERROR: changes.txt not found")
        return 1

    requirements = changes_path.read_text(encoding="utf-8")
    config = load_config(str(config_path))

    # Use existing workspace clone if available
    work_dir = project_root / config["workflow"]["work_dir"]
    repos = list(work_dir.glob("*")) if work_dir.exists() else []
    repo_dirs = [d for d in repos if d.is_dir() and not d.name.startswith(".")]
    if not repo_dirs:
        print("ERROR: No cloned repos in workspace. Run main.py once to clone.")
        return 1

    # Prefer beginner-friendly or first available
    repo_path = None
    for d in repo_dirs:
        if "beginner" in d.name.lower() or "petclinic" in d.name.lower():
            repo_path = str(d)
            break
    if not repo_path:
        repo_path = str(repo_dirs[0])

    print(f"Using repo: {Path(repo_path).name}\n")

    # --- Legacy mode (use_pipeline=false) ---
    cfg_legacy = {**config, "context": {**config.get("context", {}), "use_pipeline": False}}
    ctx_legacy = build_context(repo_path, requirements, cfg_legacy, grep_patterns=[])
    assert len(ctx_legacy) > 0, "Legacy context should not be empty"
    assert "No code files found" not in ctx_legacy or "python" in repo_path.lower()
    print(f"[OK] Legacy mode: context length = {len(ctx_legacy)} chars")

    # --- Pipeline mode (use_pipeline=true) ---
    cfg_pipeline = {**config, "context": {**config.get("context", {}), "use_pipeline": True}}
    enrichers = get_enabled_enrichers(cfg_pipeline)
    assert len(enrichers) >= 2, "Pipeline should have BaseLoader + at least GrepEnricher"
    print(f"[OK] Pipeline enrichers: {[e.__class__.__name__ for e in enrichers]}")

    ctx_pipeline = build_context(repo_path, requirements, cfg_pipeline, grep_patterns=[])
    assert len(ctx_pipeline) > 0, "Pipeline context should not be empty"
    print(f"[OK] Pipeline mode: context length = {len(ctx_pipeline)} chars")

    # Pipeline should include base loader content
    assert "## " in ctx_pipeline or "### " in ctx_pipeline or ".py" in ctx_pipeline or ".java" in ctx_pipeline

    # Grep enricher may add sections if requirements have identifiers
    if "Grep results" in ctx_pipeline or "factorial" in ctx_pipeline.lower():
        print("[OK] Grep enricher contributed (patterns from requirements)")

    print("\nAll verification checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
