#!/usr/bin/env python3
"""
Autonomous Code Generation - Main Orchestrator

Workflow:
1. Load config.ini and changes.txt
2. Clone repository
3. Create feature branch
4. Analyze codebase (with optional grep) + requirements (AI)
5. Apply generated changes
6. Run tests (Python: pytest/unittest, Java: maven/gradle)
7. On failure: error analysis → regenerate → retry (up to max_regenerate_attempts)
8. Commit and push
9. Create Pull Request
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config_loader import load_config, load_changes_with_reference, parse_testing_strategy_from_changes
from src.git_ops import (
    clone_repo,
    checkout_branch,
    stage_and_commit,
    push_branch,
    generate_branch_name,
    get_repo_name,
)
from src.pr_platform import get_pr_platform
from src.code_analyzer import (
    load_codebase_context,
    generate_changes,
    apply_changes,
    regenerate_with_error_analysis,
)
from src.project_consciousness import build_or_load_consciousness
from src.agent_analyzer import generate_changes_with_agent
from src.code_search import grep, format_grep_results
from src.code_executor import run_tests, detect_project_type, detect_build_tool
from src.activity import (
    header,
    step,
    spinner,
    log_info,
    log_success,
    log_error,
    log_warning,
)
from src.reference_pr import get_reference_pr_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous code generation and PR creation")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--changes", default="changes.txt", help="Path to changes.txt")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and generate changes only, no push/PR")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test run and regeneration loop")
    parser.add_argument("--reference-pr", "-r", help="GitHub PR URL to use as template for repetitive changes")
    parser.add_argument("--agent", "-a", action="store_true", help="Use agent mode: AI iteratively reads files, greps, explores before generating")
    parser.add_argument("--testing-strategy", "-t", choices=["bdd", "contract", "integration", "unit", "e2e", "soap", "auto"],
                       help="Java testing strategy (default: auto or from config/changes)")
    parser.add_argument("--rebuild-consciousness", action="store_true", help="Force rebuild of project consciousness cache")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    os.chdir(project_root)

    # Load config and requirements
    try:
        config = load_config(args.config)
        requirements, reference_pr_from_file, framework_repo_url, framework_branch = load_changes_with_reference(args.changes)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    repo_cfg = config["repository"]
    creds = config["github_config"]
    ai_cfg = config["ai"]
    workflow = config["workflow"]
    testing_cfg = config.get("testing") or {}

    repo_url = repo_cfg["repo_url"]
    if not repo_url or repo_url == "https://github.com/owner/repo.git":
        print("Error: Set repo_url in config.ini to your actual repository URL")
        return 1

    auth_token = creds["auth_token"]
    if not auth_token and not args.dry_run:
        print("Error: Set auth_token in config.ini or GITHUB_TOKEN/BITBUCKET_APP_PASSWORD env var")
        return 1

    if not ai_cfg.get("api_key"):
        env_var = ai_cfg.get("api_key_env", "OPENAI_API_KEY")
        print(f"Error: Set {env_var} environment variable or api_key in config.ini [ai] section")
        return 1

    work_dir = Path(workflow["work_dir"]).resolve()
    repo_name = get_repo_name(repo_url)
    clone_path = work_dir / repo_name.replace("/", "-")

    base_branch = repo_cfg["base_branch"] or "main"
    feature_branch = repo_cfg["feature_branch"] or generate_branch_name()

    header("Autonomous Code Generation", f"Repository: {repo_url}\nBranch: {feature_branch} → {base_branch}")

    # Clone (try main then master if base_branch fails)
    try:
        if clone_path.exists():
            with step("Cleaning workspace", str(clone_path)):
                shutil.rmtree(clone_path)
        work_dir.mkdir(parents=True, exist_ok=True)

        with spinner("Cloning repository"):
            last_err = None
            for try_branch in [base_branch, "main", "master"]:
                if clone_path.exists():
                    shutil.rmtree(clone_path, ignore_errors=True)
                try:
                    repo = clone_repo(
                        repo_url,
                        str(clone_path),
                        branch=try_branch,
                        auth_token=auth_token if auth_token else None,
                    )
                    if try_branch != base_branch:
                        log_info(f"Used branch '{try_branch}' (base_branch '{base_branch}' not found)")
                    break
                except Exception as br_err:
                    last_err = br_err
                    if try_branch == "master":
                        raise last_err
    except Exception as e:
        log_error(f"Clone failed: {e}")
        return 1

    with step("Creating feature branch", feature_branch):
        checkout_branch(repo, feature_branch, create=True)

    # Clone framework repo if specified in changes.txt
    framework_path = None
    framework_context = ""
    if framework_repo_url:
        try:
            framework_name = get_repo_name(framework_repo_url).replace("/", "-")
            framework_dir = work_dir / ".framework-ref" / framework_name
            if framework_dir.exists():
                shutil.rmtree(framework_dir)
            framework_dir.parent.mkdir(parents=True, exist_ok=True)
            with spinner(f"Cloning framework: {framework_repo_url}"):
                clone_repo(
                    framework_repo_url,
                    str(framework_dir),
                    branch=framework_branch or "main",
                    auth_token=auth_token if auth_token else None,
                )
            framework_path = framework_dir
            framework_consciousness = build_or_load_consciousness(
                str(framework_path),
                config,
                repo_url=framework_repo_url,
                force_rebuild=getattr(args, "rebuild_consciousness", False),
            )
            framework_context = framework_consciousness.to_context_string()
            if framework_context:
                framework_context = (
                    "\n\n## Framework context (REFERENCE ONLY – do NOT modify)\n"
                    "Use this to understand patterns, conventions, and APIs. You MUST NOT propose any changes to framework files.\n\n"
                    + framework_context
                )
                log_info("Included framework consciousness as reference")
        except Exception as e:
            log_warning(f"Could not clone/build framework: {e}. Proceeding without framework context.")

    with step("Analyzing codebase"):
        context = load_codebase_context(str(clone_path))
        grep_patterns = workflow.get("grep_patterns") or []
        if isinstance(grep_patterns, str) and grep_patterns.strip():
            grep_patterns = [p.strip() for p in grep_patterns.split(",") if p.strip()]
        if grep_patterns:
            for pattern in grep_patterns[:5]:
                results = grep(str(clone_path), pattern, context_lines=2)
                if results:
                    context += f"\n\n## Grep results for '{pattern}':\n{format_grep_results(results)[:4000]}"
        # Build or load project consciousness (structure, conventions, samples)
        consciousness = build_or_load_consciousness(
            str(clone_path),
            config,
            repo_url=repo_url,
            force_rebuild=getattr(args, "rebuild_consciousness", False),
        )
        consciousness_str = consciousness.to_context_string()
        if consciousness_str:
            context += f"\n\n{consciousness_str}"
            log_info("Included project consciousness (structure, conventions, samples)")
    log_info(f"Loaded {len(context)} chars of context")

    # Fetch reference PR if specified (CLI > config > changes file)
    reference_pr_url = args.reference_pr or workflow.get("reference_pr") or reference_pr_from_file or ""
    reference_pr_content = ""
    if reference_pr_url and auth_token:
        with step("Fetching reference PR", reference_pr_url[:60] + "..." if len(reference_pr_url) > 60 else reference_pr_url):
            reference_pr_content = get_reference_pr_context(reference_pr_url, auth_token)
        if reference_pr_content:
            log_info(f"Using reference PR as template ({len(reference_pr_content)} chars)")
        else:
            log_warning("Could not fetch reference PR; proceeding without it")

    # Analyze → Change → Test → Error analysis → Regenerate loop
    max_retries = 0 if args.skip_tests else (testing_cfg.get("max_regenerate_attempts", 3) or 0)
    test_timeout = testing_cfg.get("test_timeout", 120)
    run_tests_enabled = testing_cfg.get("run_tests", True) and not args.skip_tests

    changes = None
    modified = []
    testing_strategy = (
        args.testing_strategy
        or parse_testing_strategy_from_changes(requirements)
        or testing_cfg.get("testing_strategy", "auto")
    )
    build_tool = detect_build_tool(str(clone_path))  # maven or gradle for Java

    for attempt in range(max_retries + 1):
        if attempt == 0:
            use_agent = args.agent or workflow.get("use_agent", False)
            if use_agent:
                with spinner("Agent exploring codebase and generating changes"):
                    changes = generate_changes_with_agent(
                        requirements,
                        str(clone_path),
                        llm_config=ai_cfg,
                        reference_pr_content=reference_pr_content,
                        verbose=ai_cfg["verbose"],
                        testing_strategy=testing_strategy,
                        build_tool=build_tool,
                        consciousness_context=consciousness_str or "",
                        framework_context=framework_context,
                    )
            else:
                with spinner("Generating changes with AI"):
                    changes = generate_changes(
                        requirements,
                        context,
                        llm_config=ai_cfg,
                        verbose=ai_cfg["verbose"],
                        reference_pr_content=reference_pr_content,
                        framework_context=framework_context,
                        testing_strategy=testing_strategy,
                        build_tool=build_tool,
                    )
        else:
            with spinner(f"Regenerating (attempt {attempt + 1}/{max_retries + 1}) after test failure"):
                changes = regenerate_with_error_analysis(
                    requirements,
                    context,
                    error_output=error_output,
                    previous_changes=changes or [],
                    llm_config=ai_cfg,
                    verbose=ai_cfg["verbose"],
                    reference_pr_content=reference_pr_content,
                    framework_context=framework_context,
                    testing_strategy=testing_strategy,
                    build_tool=build_tool,
                )

        if not changes:
            log_error("No changes generated. Check requirements and codebase context.")
            return 1

        log_success(f"Generated {len(changes)} file change(s)")
        with step("Applying changes", ", ".join((c.get("path", "?") for c in changes[:5]))):
            modified = apply_changes(str(clone_path), changes)
        log_info(f"Modified: {', '.join(modified)}")

        if not run_tests_enabled or args.dry_run:
            break

        ptype = detect_project_type(str(clone_path))
        with step("Running tests", f"{ptype}"):
            exit_code, stdout, stderr = run_tests(str(clone_path), ptype, timeout=test_timeout)
        combined_output = f"stdout:\n{stdout}\n\nstderr:\n{stderr}"

        if exit_code == 0:
            log_success("Tests passed")
            break

        error_output = combined_output
        log_warning(f"Tests failed (exit {exit_code})")
        log_info(combined_output[:800] + "..." if len(combined_output) > 800 else combined_output)

        if attempt >= max_retries:
            log_warning(f"Max regeneration attempts ({max_retries}) reached. Proceeding.")
            break

        # Refresh context after changes for regeneration (include consciousness)
        context = load_codebase_context(str(clone_path))
        consciousness = build_or_load_consciousness(str(clone_path), config, repo_url=repo_url)
        consciousness_str = consciousness.to_context_string()
        if consciousness_str:
            context += f"\n\n{consciousness_str}"

    if args.dry_run:
        log_success("Dry run complete. No commit, push, or PR.")
        return 0

    issue_ref = os.environ.get("AUTO_PR_ISSUE", "")
    commit_msg = f"Auto: Implement changes from changes.txt\n\nModified: {', '.join(modified)}"
    if issue_ref:
        commit_msg += f"\n\nFixes #{issue_ref}"

    with step("Committing changes"):
        stage_and_commit(repo, commit_msg)

    try:
        with step("Pushing branch", feature_branch):
            push_branch(repo, feature_branch)
    except Exception as e:
        log_error(f"Push failed: {e}")
        return 1

    # Create PR
    platform = get_pr_platform(repo_cfg["platform"], auth_token)
    # Smart PR title from modified files
    if any("factorial" in p.lower() for p in modified):
        pr_title = "Add factorial.py"
    elif any("stringutils" in p.lower() for p in modified):
        pr_title = "Add StringUtils with email validation"
    else:
        pr_title = "Implement changes from changes.txt"
    pr_desc = f"Autonomous code generation based on requirements in changes.txt.\n\n**Modified files:**\n" + "\n".join(f"- {p}" for p in modified)
    if issue_ref:
        pr_desc += f"\n\nFixes #{issue_ref}"
    pr_url = platform.create_pull_request(
        repo_url=repo_url,
        source_branch=feature_branch,
        target_branch=base_branch,
        title=pr_title,
        description=pr_desc,
    )

    if pr_url:
        log_success(f"Pull Request created: {pr_url}")
    else:
        log_warning("PR creation failed. Branch was pushed; create PR manually.")

    if workflow["cleanup_after_pr"] and clone_path.exists():
        with step("Cleaning workspace"):
            shutil.rmtree(clone_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
