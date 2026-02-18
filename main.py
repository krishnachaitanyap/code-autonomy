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
from src.platform.git_ops import (
    clone_repo,
    checkout_branch,
    stage_and_commit,
    push_branch,
    generate_branch_name,
    get_repo_name,
)
from src.platform.pr_platform import get_pr_platform
from src.code.analyzer import (
    generate_changes,
    apply_changes,
    regenerate_with_error_analysis,
)
from src.context import build_context
from src.consciousness.core import build_or_load_consciousness
from src.agent.analyzer import generate_changes_with_agent, generate_plan_with_agent, generate_answer_with_agent
from src.agent.knowledge import load_repo_knowledge
from src.code.executor import run_tests, detect_project_type, detect_build_tool
from src.agent.activity import (
    header,
    step,
    spinner,
    log_info,
    log_success,
    log_error,
    log_warning,
    log_llm_stats,
    log_checkpoint_saved,
)
from src.platform.reference_pr import get_reference_pr_context
from src.startup_validator import validate_startup
from src.llm_client import configure_resiliency


def _build_requirements_from_story(story: dict) -> str:
    """Convert a JIRA story dict into an agent requirements string."""
    parts = [f"# {story['key']}: {story['summary']}"]
    if story.get("description"):
        parts.append(f"\n## Description\n{story['description']}")
    if story.get("acceptance_criteria"):
        parts.append(f"\n## Acceptance Criteria\n{story['acceptance_criteria']}")
    return "\n".join(parts)


def _run_jira_mode(args) -> int:
    """Pull stories from JIRA and process each with the agent."""
    from src.jira.client import (
        fetch_agent_stories,
        get_jira_token,
        add_jira_comment,
        transition_jira_issue,
    )
    from src.jira.session import (
        JiraSession,
        create_jira_session,
        save_jira_session,
        load_jira_session,
        clear_jira_session,
        STATUS_PENDING,
        STATUS_IN_PROGRESS,
        STATUS_SUCCESS,
        STATUS_FAILED,
    )
    from src.consciousness.core import build_or_load_consciousness
    from src.agent.knowledge import load_repo_knowledge, compute_repo_id

    project_root = Path(__file__).parent
    os.chdir(project_root)

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    jira_cfg = config.get("jira") or {}
    if not jira_cfg.get("base_url"):
        log_error(
            "Missing [jira] section in config.ini. "
            "Copy the [jira] block from config.example.ini and fill in your values."
        )
        return 1

    ai_cfg = config["ai"]
    agent_cfg_section = config.get("agent") or {}

    # Bitbucket Server integration (optional)
    bb_cfg = config.get("bitbucket") or {}
    bb_enabled = bb_cfg.get("enabled", False)
    bb_repo: "Repo | None" = None

    # Resolve repo path — Bitbucket can clone for us if no --repo-path
    if bb_enabled and not args.repo_path:
        from src.jira.bitbucket_bridge import clone_bitbucket_repo
        clone_url = bb_cfg.get("clone_url", "")
        if not clone_url:
            # Derive clone URL from base_url + project_key + repo_slug
            # Strip any path from base_url to get just the scheme + host
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(bb_cfg["base_url"].rstrip("/"))
            bb_origin = f"{_parsed.scheme}://{_parsed.hostname}"
            if _parsed.port:
                bb_origin += f":{_parsed.port}"
            pkey = bb_cfg["project_key"]
            rslug = bb_cfg["repo_slug"]
            protocol = bb_cfg.get("clone_protocol", "ssh")
            if protocol == "ssh":
                # Standard Bitbucket Server SSH URL
                clone_url = f"ssh://git@{_parsed.hostname}:7999/{pkey}/{rslug}.git"
            else:
                clone_url = f"{bb_origin}/scm/{pkey}/{rslug}.git"

        work_dir = Path(config.get("workflow", {}).get("work_dir", "./workspace")).resolve()
        target_dir = work_dir / f"jira-{bb_cfg.get('repo_slug', 'repo')}"

        with spinner("Cloning from Bitbucket Server"):
            try:
                bb_repo = clone_bitbucket_repo(
                    clone_url,
                    str(target_dir),
                    branch=bb_cfg.get("base_branch", "main"),
                    auth_token=bb_cfg.get("user_token", ""),
                    protocol=bb_cfg.get("clone_protocol", "ssh"),
                )
                clone_path = target_dir.resolve()
                log_success(f"Cloned to {clone_path}")
            except Exception as e:
                log_error(f"Bitbucket clone failed: {e}")
                return 1
    elif args.repo_path:
        clone_path = Path(args.repo_path).resolve()
    else:
        log_error("--repo-path is required when using --jira mode (unless [bitbucket] is enabled)")
        return 1

    if not clone_path.is_dir():
        log_error(f"Repo path is not a directory: {clone_path}")
        return 1

    # Open as Repo object if Bitbucket is enabled and we haven't already
    if bb_enabled and bb_repo is None:
        try:
            from git import Repo as _Repo
            bb_repo = _Repo(str(clone_path))
        except Exception:
            log_warning("Could not open clone_path as git repo — Bitbucket git ops disabled")
            bb_enabled = False

    # Detect repo_url from git remote
    repo_url = ""
    try:
        import subprocess as _sp
        _out = _sp.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(clone_path), capture_output=True, text=True,
        )
        if _out.returncode == 0 and _out.stdout.strip():
            repo_url = _out.stdout.strip()
    except Exception:
        pass

    header("JIRA Mode", f"Repo: {clone_path}" + (" (Bitbucket Server)" if bb_enabled else ""))

    # Pre-flight validation
    from src.startup_validator import validate_startup
    validation = validate_startup(config, dry_run=False, using_local_repo=True)
    for w in validation.warnings:
        log_warning(w)
    if not validation.is_valid:
        for e in validation.errors:
            log_error(e)
        return 1

    # Initialize resiliency
    configure_resiliency(
        circuit_breaker_threshold=int(agent_cfg_section.get("circuit_breaker_threshold", 5)),
        circuit_breaker_timeout=float(agent_cfg_section.get("circuit_breaker_timeout", 60.0)),
        rate_limit_max_tokens=float(agent_cfg_section.get("rate_limit_max_tokens", 10.0)),
        rate_limit_refill_rate=float(agent_cfg_section.get("rate_limit_refill_rate", 1.0)),
    )

    # Authenticate to JIRA
    with spinner("Authenticating to JIRA"):
        try:
            token = get_jira_token(config)
        except Exception as e:
            log_error(f"JIRA authentication failed: {e}")
            return 1
    log_success("JIRA authentication successful")

    # Compute repo_id for session tracking
    repo_id = compute_repo_id(str(clone_path), repo_url)

    # Resume: load saved session if --resume is set
    resume_mode = getattr(args, "resume", False)
    session: JiraSession | None = None
    stories: list[dict] = []
    # Accumulate working memory from all completed stories so subsequent
    # stories benefit from file understanding gathered in earlier runs.
    accumulated_wm: dict[str, str] = {}

    if resume_mode:
        session = load_jira_session(repo_id)
        if session and session.resumable_stories():
            succeeded = session.succeeded_stories()
            resumable = session.resumable_stories()
            failed_count = sum(1 for s in resumable if s.status == STATUS_FAILED)
            log_info(
                f"Resuming JIRA session: {len(succeeded)} succeeded, "
                f"{len(resumable)} remaining"
                + (f" ({failed_count} previously failed)" if failed_count else "")
            )
            # Reset failed stories back to pending so they are retried
            # (preserve working_memory — it contains useful file understanding)
            for s in resumable:
                if s.status == STATUS_FAILED:
                    s.status = STATUS_PENDING
                    s.error = ""
            save_jira_session(session)
            # Seed accumulated working memory from ALL prior stories (even failed)
            for s in session.stories:
                if s.working_memory:
                    accumulated_wm.update(s.working_memory)
            # Re-fetch full story data from JIRA for resumable stories
            resumable_keys = {s.key for s in resumable}
            with spinner("Fetching stories from JIRA"):
                try:
                    all_stories = fetch_agent_stories(config, token=token)
                except Exception as e:
                    log_error(f"Failed to fetch JIRA stories: {e}")
                    return 1
            stories = [s for s in all_stories if s["key"] in resumable_keys]
            if not stories:
                log_info("No resumable stories found in JIRA. Session complete.")
                clear_jira_session(repo_id)
                return 0
            log_info(f"Found {len(stories)} story(ies) to resume")
        else:
            log_info("No resumable JIRA session found — starting fresh")
            resume_mode = False  # fall through to fresh start

    if not resume_mode or not stories:
        # Fresh start: fetch stories from JIRA
        with spinner("Fetching stories from JIRA"):
            try:
                stories = fetch_agent_stories(config, token=token)
            except Exception as e:
                log_error(f"Failed to fetch JIRA stories: {e}")
                return 1

        if not stories:
            log_info("No stories found matching the agent label. Nothing to do.")
            return 0

        log_info(f"Found {len(stories)} story(ies) to process")

        # Create and save a fresh session
        session = create_jira_session(repo_id, stories)
        save_jira_session(session)

    # Build consciousness and code index once (shared across stories)
    with step("Analyzing codebase"):
        consciousness = build_or_load_consciousness(
            str(clone_path), config, repo_url=repo_url,
        )
        log_info("Loaded project consciousness")

        code_index = None
        try:
            from src.code_index import build_or_load_code_index
            code_index = build_or_load_code_index(
                str(clone_path), config, repo_url=repo_url,
                consciousness=consciousness,
            )
            log_info(f"Loaded code index ({code_index.total_symbols} symbols)")
        except Exception as _ci_err:
            log_warning(f"Could not build code index: {_ci_err}")

        repo_knowledge = load_repo_knowledge(str(clone_path))

    # Agent config (reused per story)
    skip_tests = getattr(args, "skip_tests", False) or agent_cfg_section.get("skip_tests", False)
    agent_config = {
        "max_turns": int(agent_cfg_section.get("max_turns", 50)),
        "smart_summarization": agent_cfg_section.get("smart_summarization", True),
        "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
        "command_allowlist_only": agent_cfg_section.get("command_allowlist_only", False),
        "allowed_command_prefixes": agent_cfg_section.get("allowed_command_prefixes", []),
        "blocked_commands": agent_cfg_section.get("blocked_commands", []),
        "summarization_budget": int(agent_cfg_section.get("summarization_budget", 0)),
        "testing_budget": int(agent_cfg_section.get("testing_budget", 0)),
        "skip_tests": skip_tests,
    }

    # Collect results from previously succeeded stories (for summary)
    results: list[dict] = []
    if resume_mode and session:
        for s in session.succeeded_stories():
            results.append({
                "key": s.key,
                "status": "success",
                "files": s.files_changed,
                "resumed": True,
            })

    # Process each story
    for i, story in enumerate(stories, 1):
        key = story["key"]
        log_info(f"\n[{i}/{len(stories)}] Processing {key}: {story['summary']}")

        # Mark story as in_progress in session
        if session:
            session.mark_story(key, STATUS_IN_PROGRESS)
            save_jira_session(session)

        requirements = _build_requirements_from_story(story)

        # Transition to "In Progress" if configured
        if jira_cfg.get("auto_transition_start"):
            try:
                transition_jira_issue(config, key, "In Progress", token=token)
                log_info(f"  Transitioned {key} → In Progress")
            except Exception as te:
                log_warning(f"  Could not transition {key}: {te}")

        # Create a feature branch for this story (Bitbucket flow)
        story_branch = ""
        if bb_enabled and bb_repo:
            try:
                from src.jira.bitbucket_bridge import prepare_story_branch
                _bb_pull_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
                story_branch = prepare_story_branch(
                    bb_repo, key, bb_cfg.get("base_branch", "main"),
                    auth_token=_bb_pull_token,
                )
                log_info(f"  Created branch: {story_branch}")
            except Exception as be:
                log_error(f"  {key}: Could not create branch — {be}")
                results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})
                if session:
                    session.mark_story(key, STATUS_FAILED, error=f"branch creation: {be}")
                    save_jira_session(session)
                continue

        # Determine if first attempt should resume (from a prior interrupted run)
        story_was_in_progress = False
        if resume_mode and session:
            ss = session.get_story(key)
            if ss and ss.status == STATUS_IN_PROGRESS:
                story_was_in_progress = True

        # Run agent (with auto-retry via resume on turn exhaustion)
        max_retries = int(jira_cfg.get("max_retries", 2))
        result = None
        try:
            for attempt in range(1, max_retries + 1):
                # Resume if: retrying after turn exhaustion OR resuming an interrupted story
                is_resume = attempt > 1 or (attempt == 1 and story_was_in_progress)
                if attempt == 1 and story_was_in_progress:
                    label = f"Agent resuming {key} (from previous session)"
                elif attempt == 1:
                    label = f"Agent working on {key}"
                else:
                    label = f"Agent resuming {key} (attempt {attempt}/{max_retries})"
                with spinner(label):
                    result = generate_changes_with_agent(
                        requirements,
                        str(clone_path),
                        llm_config=ai_cfg,
                        verbose=ai_cfg.get("verbose", False),
                        consciousness=consciousness,
                        agent_config=agent_config,
                        config=config,
                        repo_url=repo_url,
                        repo_knowledge=repo_knowledge,
                        code_index=code_index,
                        resume=is_resume,
                        initial_working_memory=accumulated_wm or None,
                    )

                if result.success:
                    break

                # Only retry if agent ran out of turns (checkpoint saved) and made partial progress
                if result.checkpoint and result.files_changed and attempt < max_retries:
                    log_warning(f"  {key}: Agent ran out of turns ({len(result.files_changed)} file(s) so far) — resuming...")
                else:
                    break
        except Exception as exc:
            log_error(f"  {key}: Agent crashed — {exc}")
            # Discard changes and return to base branch
            if bb_enabled and bb_repo:
                from src.jira.bitbucket_bridge import discard_story_changes
                discard_story_changes(bb_repo, bb_cfg.get("base_branch", "main"))
            # Save crash context to session so resume can pick it up
            if session:
                session.mark_story(key, STATUS_FAILED, error=f"crash: {exc}")
                save_jira_session(session)
            results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})
            continue

        # Accumulate working memory from this story's run (success or failure)
        if result.working_memory:
            accumulated_wm.update(result.working_memory)

        if result.success:
            log_success(f"  {key}: Agent completed — {len(result.files_changed)} file(s) modified")

            # Bitbucket: commit, push, create PR
            pr_url = ""
            if bb_enabled and bb_repo and story_branch:
                from src.jira.bitbucket_bridge import commit_and_push_story, create_story_pr
                _bb_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
                pushed = commit_and_push_story(
                    bb_repo, story_branch, key,
                    result.summary, result.files_changed,
                    auth_token=_bb_token,
                )
                if pushed:
                    log_success(f"  {key}: Pushed branch {story_branch}")
                    pr_url = create_story_pr(
                        bb_cfg, repo_url, story_branch,
                        bb_cfg.get("base_branch", "main"),
                        key, story["summary"], result.summary,
                    ) or ""
                    if pr_url:
                        log_success(f"  {key}: PR created → {pr_url}")
                    else:
                        log_warning(f"  {key}: Push succeeded but PR creation failed")
                else:
                    log_warning(f"  {key}: No changes to commit/push")

            # Update session state (including working memory for resume)
            if session:
                session.mark_story(key, STATUS_SUCCESS, files_changed=len(result.files_changed))
                story_state = session.get_story(key)
                if story_state and result.working_memory:
                    story_state.working_memory = result.working_memory
                save_jira_session(session)

            # Add success comment to JIRA (include PR URL if available)
            comment = (
                f"[code-autonomy] Agent completed successfully.\n"
                f"Files modified: {', '.join(result.files_changed) or 'none'}\n"
                f"Summary: {result.summary}"
            )
            if pr_url:
                comment += f"\nPull Request: {pr_url}"
            try:
                add_jira_comment(config, key, comment, token=token)
            except Exception as ce:
                log_warning(f"  Could not comment on {key}: {ce}")

            # Transition to "Done" if configured
            if jira_cfg.get("auto_transition_done"):
                try:
                    transition_jira_issue(config, key, "Done", token=token)
                    log_info(f"  Transitioned {key} → Done")
                except Exception as te:
                    log_warning(f"  Could not transition {key}: {te}")

            results.append({"key": key, "status": "success", "files": len(result.files_changed), "pr_url": pr_url})
        else:
            log_error(f"  {key}: Agent did not complete — {result.summary}")

            # Discard changes and return to base branch
            if bb_enabled and bb_repo:
                from src.jira.bitbucket_bridge import discard_story_changes
                discard_story_changes(bb_repo, bb_cfg.get("base_branch", "main"))

            # Update session state (including working memory for resume)
            if session:
                session.mark_story(key, STATUS_FAILED, error=result.summary)
                story_state = session.get_story(key)
                if story_state and result.working_memory:
                    story_state.working_memory = result.working_memory
                save_jira_session(session)

            # Add failure comment to JIRA
            comment = (
                f"[code-autonomy] Agent did not complete.\n"
                f"Error: {result.summary}"
            )
            try:
                add_jira_comment(config, key, comment, token=token)
            except Exception as ce:
                log_warning(f"  Could not comment on {key}: {ce}")

            results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})

    # Clear session only if all stories succeeded; otherwise persist for --resume
    if session:
        if session.all_succeeded():
            clear_jira_session(repo_id)
        else:
            save_jira_session(session)
            failed_count = len([r for r in results if r["status"] == "failed"])
            if failed_count:
                log_info(
                    f"Session saved — {failed_count} story(ies) failed. "
                    f"Run with --jira --resume to retry."
                )

    # Summary
    print(f"\n{'=' * 60}")
    print("JIRA Processing Summary")
    print(f"{'=' * 60}")
    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"  Total: {len(results)}  |  Succeeded: {succeeded}  |  Failed: {failed}")
    print(f"{'─' * 60}")
    for r in results:
        icon = "OK" if r["status"] == "success" else "FAIL"
        pr_info = f"  PR: {r['pr_url']}" if r.get("pr_url") else ""
        print(f"  [{icon}] {r['key']}  ({r['files']} files){pr_info}")
    print(f"{'=' * 60}\n")

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous code generation and PR creation")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--changes", default="changes.txt", help="Path to changes.txt")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and generate changes only, no push/PR")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test run and regeneration loop")
    parser.add_argument("--reference-pr", "-r", help="GitHub PR URL to use as template for repetitive changes")
    parser.add_argument("--repo-path", help="Path to an existing local repository (skips clone, branch creation, and push/PR)")
    parser.add_argument("--agent", "-a", action="store_true", help="Use agent mode: AI explores, edits, tests, and fixes code in a single loop (Claude-Code-like)")
    parser.add_argument("--plan", "-p", nargs="?", const=True, default=None,
                        help="Plan mode: agent explores read-only and proposes changes. Accepts optional inline prompt: --plan \"Add auth\"")
    parser.add_argument("--ask", "-q", nargs="?", const=True, default=None,
                        help="Ask mode: agent answers questions about the codebase. Accepts optional inline prompt: --ask \"How does auth work?\"")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve plan without prompting (use with --plan)")
    parser.add_argument("--testing-strategy", "-t", choices=["bdd", "contract", "integration", "unit", "e2e", "soap", "auto"],
                       help="Java testing strategy (default: auto or from config/changes)")
    parser.add_argument("--rebuild-consciousness", action="store_true", help="Force rebuild of project consciousness cache")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last checkpoint (requires same requirement)")
    parser.add_argument("--init-knowledge", action="store_true",
                        help="Generate a .code-autonomy.md repo knowledge file from project analysis")
    parser.add_argument("--jira", action="store_true",
                        help="Pull stories from JIRA labeled for code-autonomy and process each with the agent")
    args = parser.parse_args()

    # --init-knowledge: generate .code-autonomy.md and exit (no config needed)
    if args.init_knowledge:
        from src.consciousness.core import build_consciousness
        from src.agent.knowledge_generator import (
            detect_existing_knowledge_file,
            generate_knowledge_markdown,
            write_knowledge_file,
        )

        target_path = Path(args.repo_path).resolve() if args.repo_path else Path.cwd()
        if not target_path.is_dir():
            log_error(f"Target directory does not exist: {target_path}")
            return 1

        header("Init Knowledge", f"Target: {target_path}")

        existing = detect_existing_knowledge_file(str(target_path))
        if existing:
            log_warning(f"Knowledge file already exists: {existing}")
            log_info("Remove it first if you want to regenerate.")
            return 0

        with spinner("Analyzing project structure"):
            consciousness = build_consciousness(str(target_path))

        content = generate_knowledge_markdown(consciousness)
        output_path = write_knowledge_file(str(target_path), content)

        log_success(f"Created {output_path} ({len(content)} chars)")
        log_info("Look for <!-- TODO --> markers and fill in project-specific details.")
        return 0

    # --jira: pull stories from JIRA and process each with the agent
    if args.jira:
        return _run_jira_mode(args)

    project_root = Path(__file__).parent
    os.chdir(project_root)

    # Inline prompt from --plan "..." or --ask "..." overrides changes.txt
    inline_prompt = None
    if isinstance(args.plan, str):
        inline_prompt = args.plan
    elif isinstance(args.ask, str):
        inline_prompt = args.ask

    # Load config and requirements
    try:
        config = load_config(args.config)
        if inline_prompt:
            requirements = inline_prompt
            reference_pr_from_file = ""
            framework_repo_url = ""
            framework_branch = ""
        else:
            requirements, reference_pr_from_file, framework_repo_url, framework_branch = load_changes_with_reference(args.changes)
    except FileNotFoundError as e:
        if inline_prompt:
            # changes.txt not found is fine when inline prompt is provided
            requirements = inline_prompt
            reference_pr_from_file = ""
            framework_repo_url = ""
            framework_branch = ""
        else:
            print(f"Error: {e}")
            return 1

    repo_cfg = config["repository"]
    creds = config["github_config"]
    ai_cfg = config["ai"]
    workflow = config["workflow"]
    testing_cfg = config.get("testing") or {}

    using_local_repo = bool(args.repo_path)

    # Pre-flight validation
    validation = validate_startup(config, dry_run=args.dry_run, using_local_repo=using_local_repo)
    for w in validation.warnings:
        log_warning(w)
    if not validation.is_valid:
        for e in validation.errors:
            log_error(e)
        return 1

    # Initialize resiliency (circuit breaker + rate limiter)
    agent_cfg = config.get("agent") or {}
    configure_resiliency(
        circuit_breaker_threshold=int(agent_cfg.get("circuit_breaker_threshold", 5)),
        circuit_breaker_timeout=float(agent_cfg.get("circuit_breaker_timeout", 60.0)),
        rate_limit_max_tokens=float(agent_cfg.get("rate_limit_max_tokens", 10.0)),
        rate_limit_refill_rate=float(agent_cfg.get("rate_limit_refill_rate", 1.0)),
    )

    if using_local_repo:
        # --repo-path: use existing local directory, skip clone/branch/push/PR
        local_path = Path(args.repo_path).resolve()
        if not local_path.is_dir():
            print(f"Error: --repo-path is not a directory: {local_path}")
            return 1

        clone_path = local_path

        # Try to detect repo_url from git remote
        repo_url = repo_cfg.get("repo_url", "")
        if not repo_url or repo_url == "https://github.com/owner/repo.git":
            try:
                import subprocess as _sp
                _out = _sp.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=str(local_path), capture_output=True, text=True,
                )
                if _out.returncode == 0 and _out.stdout.strip():
                    repo_url = _out.stdout.strip()
            except Exception:
                pass
            if not repo_url:
                repo_url = ""  # Not required for local-only runs

        auth_token = creds.get("auth_token", "")
        # auth_token not required for local repo

        header("Autonomous Code Generation (local repo)", f"Path: {clone_path}")
    else:
        # Normal remote mode — clone the repo
        repo_url = repo_cfg["repo_url"]
        auth_token = creds["auth_token"]

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
    if framework_repo_url and not using_local_repo:
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

    use_agent = args.agent or args.plan or args.ask or workflow.get("use_agent", False)

    with step("Analyzing codebase"):
        # Build or load project consciousness (needed by all modes)
        consciousness = build_or_load_consciousness(
            str(clone_path),
            config,
            repo_url=repo_url,
            force_rebuild=getattr(args, "rebuild_consciousness", False),
        )
        log_info("Loaded project consciousness (structure, conventions, samples)")

        # Build or load code index (symbol table, dependency graph, hierarchy, embeddings)
        code_index = None
        if use_agent:
            try:
                from src.code_index import build_or_load_code_index
                code_index = build_or_load_code_index(
                    str(clone_path), config, repo_url=repo_url,
                    consciousness=consciousness,
                )
                log_info(f"Loaded code index ({code_index.total_symbols} symbols, {code_index.total_files} files)")
            except Exception as _ci_err:
                import traceback
                log_warning(f"Could not build code index: {_ci_err}. Proceeding without it.")
                log_warning(f"Code index traceback: {traceback.format_exc()}")

        # Load repo knowledge files (.code-autonomy.md, AGENT.md, or .code-autonomy/ dir)
        repo_knowledge = load_repo_knowledge(str(clone_path))
        if repo_knowledge:
            log_info(f"Included repo knowledge ({len(repo_knowledge)} chars)")

        # build_context() is only needed for standard (non-agent) mode — agent
        # modes use tools to explore the codebase, so bulk context is wasteful.
        context = ""
        if not use_agent:
            grep_patterns = workflow.get("grep_patterns") or []
            if isinstance(grep_patterns, str) and grep_patterns.strip():
                grep_patterns = [p.strip() for p in grep_patterns.split(",") if p.strip()]
            context = build_context(
                str(clone_path),
                requirements=requirements,
                config=config,
                grep_patterns=grep_patterns,
            )
            consciousness_str = consciousness.to_context_string()
            if consciousness_str:
                context += f"\n\n{consciousness_str}"
            if repo_knowledge:
                context += repo_knowledge
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

    use_plan = args.plan

    if args.ask:
        # ---------------------------------------------------------------
        # ASK MODE: agent explores read-only and answers questions
        # ---------------------------------------------------------------
        agent_cfg_section = config.get("agent") or {}
        agent_config = {
            "ask_max_turns": int(agent_cfg_section.get("ask_max_turns", 20)),
            "max_turns": int(agent_cfg_section.get("max_turns", 50)),
            "smart_summarization": agent_cfg_section.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
        }

        with spinner("Agent exploring codebase to answer your question"):
            ask_result = generate_answer_with_agent(
                requirements,
                str(clone_path),
                llm_config=ai_cfg,
                verbose=ai_cfg.get("verbose", False),
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
            )

        if ask_result.success:
            log_success(f"Answer found ({ask_result.turns_used} turns)")
            print(f"\n{'=' * 60}")
            print("ANSWER")
            print(f"{'=' * 60}")
            print(ask_result.answer)
            if ask_result.sources:
                print(f"\n{'─' * 60}")
                print("Sources consulted:")
                for src in ask_result.sources:
                    print(f"  - {src}")
            print(f"{'=' * 60}\n")
        else:
            log_error(f"Could not answer: {ask_result.summary}")

        if ask_result.usage_stats and ask_result.usage_stats.num_calls > 0:
            log_llm_stats(ask_result.usage_stats)

        return 0

    if use_plan:
        # ---------------------------------------------------------------
        # PLAN MODE: agent explores read-only, proposes changes as diffs
        # ---------------------------------------------------------------
        from src.agent.plan import apply_plan
        from src.agent.plan_display import render_plan, prompt_approval

        agent_cfg_section = config.get("agent") or {}
        agent_config = {
            "plan_max_turns": int(agent_cfg_section.get("plan_max_turns", 30)),
            "max_turns": int(agent_cfg_section.get("max_turns", 50)),
            "smart_summarization": agent_cfg_section.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
        }

        # Phase 1: Plan
        with spinner("Agent exploring codebase and proposing changes (plan mode)"):
            plan_result = generate_plan_with_agent(
                requirements,
                str(clone_path),
                llm_config=ai_cfg,
                reference_pr_content=reference_pr_content,
                verbose=ai_cfg.get("verbose", False),
                testing_strategy=testing_strategy,
                build_tool=build_tool,
                consciousness=consciousness,
                framework_context=framework_context,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
            )

        if not plan_result.success or plan_result.plan is None or plan_result.plan.is_empty:
            log_error(f"Plan mode did not produce changes: {plan_result.summary}")
            return 1

        log_success(f"Plan complete: {plan_result.summary}")
        log_info(f"Proposed changes to {len(plan_result.plan.files_affected)} file(s) in {plan_result.turns_used} turns")
        if plan_result.usage_stats and plan_result.usage_stats.num_calls > 0:
            log_llm_stats(plan_result.usage_stats)

        # Display diffs
        render_plan(plan_result.plan, str(clone_path))

        # Phase 2: Approval
        if args.auto_approve:
            choice = "approve"
            log_info("Auto-approved (--auto-approve)")
        else:
            choice = prompt_approval()

        if choice == "reject":
            log_warning("Plan rejected. No changes applied.")
            return 0

        if choice == "modify":
            # Fall back to full agent mode with plan as context
            log_info("Falling back to full agent mode with plan as starting context...")
            plan_context = "\n".join(
                f"- {c.action.value} {c.path}: {c.description}"
                for c in plan_result.plan.changes
            )
            requirements_with_plan = (
                f"{requirements}\n\n"
                f"## Previously proposed plan (use as starting point, modify as needed)\n"
                f"{plan_context}"
            )
            agent_config_full = {
                "max_turns": int(agent_cfg_section.get("max_turns", 50)),
                "smart_summarization": agent_cfg_section.get("smart_summarization", True),
                "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
                "command_allowlist_only": agent_cfg_section.get("command_allowlist_only", False),
                "allowed_command_prefixes": agent_cfg_section.get("allowed_command_prefixes", []),
                "blocked_commands": agent_cfg_section.get("blocked_commands", []),
                "summarization_budget": int(agent_cfg_section.get("summarization_budget", 0)),
                "testing_budget": int(agent_cfg_section.get("testing_budget", 0)),
            }
            with spinner("Agent implementing modified plan"):
                result = generate_changes_with_agent(
                    requirements_with_plan,
                    str(clone_path),
                    llm_config=ai_cfg,
                    reference_pr_content=reference_pr_content,
                    verbose=ai_cfg.get("verbose", False),
                    testing_strategy=testing_strategy,
                    build_tool=build_tool,
                    consciousness=consciousness,
                    framework_context=framework_context,
                    agent_config=agent_config_full,
                    config=config,
                    repo_url=repo_url,
                    repo_knowledge=repo_knowledge,
                    code_index=code_index,
                )
            if result.success:
                modified = result.files_changed
                log_success(f"Agent completed: {result.summary}")
                if result.usage_stats and result.usage_stats.num_calls > 0:
                    log_llm_stats(result.usage_stats)
            else:
                log_error(f"Agent did not complete: {result.summary}")
                return 1
        else:
            # Approve: apply all changes
            with spinner("Applying approved changes"):
                modified = apply_plan(Path(clone_path), plan_result.plan)
            log_success(f"Applied changes to {len(modified)} file(s)")

            # Optionally run tests after applying
            if run_tests_enabled and not args.dry_run:
                ptype = detect_project_type(str(clone_path))
                with step("Running tests", f"{ptype}"):
                    exit_code, stdout, stderr = run_tests(str(clone_path), ptype, timeout=test_timeout)
                if exit_code == 0:
                    log_success("Tests passed")
                else:
                    log_warning(f"Tests failed (exit {exit_code})")
                    log_info((stdout + "\n" + stderr)[:800])

    elif use_agent:
        # ---------------------------------------------------------------
        # NEW AGENT MODE: agent writes files, runs tests, fixes errors
        # inside a single agentic loop — no external retry needed.
        # ---------------------------------------------------------------
        agent_cfg_section = config.get("agent") or {}
        agent_config = {
            "max_turns": int(agent_cfg_section.get("max_turns", 50)),
            "smart_summarization": agent_cfg_section.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
            "command_allowlist_only": agent_cfg_section.get("command_allowlist_only", False),
            "allowed_command_prefixes": agent_cfg_section.get("allowed_command_prefixes", []),
            "blocked_commands": agent_cfg_section.get("blocked_commands", []),
            "summarization_budget": int(agent_cfg_section.get("summarization_budget", 0)),
            "testing_budget": int(agent_cfg_section.get("testing_budget", 0)),
            "skip_tests": args.skip_tests or agent_cfg_section.get("skip_tests", False),
        }

        with spinner("Agent exploring, implementing, and testing changes"):
            result = generate_changes_with_agent(
                requirements,
                str(clone_path),
                llm_config=ai_cfg,
                reference_pr_content=reference_pr_content,
                verbose=ai_cfg.get("verbose", False),
                testing_strategy=testing_strategy,
                build_tool=build_tool,
                consciousness=consciousness,
                framework_context=framework_context,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
                resume=args.resume,
            )

        if result.success:
            modified = result.files_changed
            log_success(f"Agent completed: {result.summary}")
            log_info(f"Modified {len(modified)} file(s) in {result.turns_used} turns")
            if result.usage_stats and result.usage_stats.num_calls > 0:
                log_llm_stats(result.usage_stats)

            # Post-edit verification gate
            if modified and not args.dry_run and not using_local_repo and code_index is not None:
                try:
                    from src.code_index import post_edit_verification_gate
                    verification = post_edit_verification_gate(
                        str(clone_path), modified, code_index, config,
                    )
                    if verification.passed:
                        log_success("Post-edit verification passed")
                    else:
                        log_warning(f"Post-edit verification issues:\n{verification.summary()}")
                        # Retry: re-invoke agent with repair instructions (max 1 retry)
                        repair_prompt = verification.repair_prompt()
                        if repair_prompt:
                            log_info("Attempting repair via agent retry...")
                            repair_requirements = (
                                f"{requirements}\n\n{repair_prompt}"
                            )
                            with spinner("Agent repairing verification failures"):
                                repair_result = generate_changes_with_agent(
                                    repair_requirements,
                                    str(clone_path),
                                    llm_config=ai_cfg,
                                    reference_pr_content=reference_pr_content,
                                    verbose=ai_cfg.get("verbose", False),
                                    max_turns=20,
                                    testing_strategy=testing_strategy,
                                    build_tool=build_tool,
                                    consciousness=consciousness,
                                    framework_context=framework_context,
                                    agent_config=agent_config,
                                    config=config,
                                    repo_url=repo_url,
                                    repo_knowledge=repo_knowledge,
                                    code_index=code_index,
                                )
                            if repair_result.success:
                                modified = list(set(modified) | set(repair_result.files_changed))
                                log_info("Re-verifying after repair...")
                                reverify = post_edit_verification_gate(
                                    str(clone_path), modified, code_index, config,
                                )
                                if reverify.passed:
                                    log_success("Post-repair verification passed")
                                else:
                                    log_warning(f"Post-repair verification still has issues:\n{reverify.summary()}")
                            else:
                                log_warning(f"Repair attempt did not complete: {repair_result.summary}")
                except Exception as _ve:
                    log_warning(f"Post-edit verification skipped: {_ve}")

        elif result.changes:
            # Backward compat: agent fell back to legacy JSON mode
            log_info("Agent used legacy JSON mode")
            changes = result.changes
            log_success(f"Generated {len(changes)} file change(s)")
            with step("Applying changes", ", ".join(c.get("path", "?") for c in changes[:5])):
                modified = apply_changes(str(clone_path), changes)
            log_info(f"Modified: {', '.join(modified)}")
        else:
            # Show checkpoint summary if one was saved
            if result.checkpoint:
                log_checkpoint_saved(result.checkpoint)
            if result.files_changed:
                # Agent made partial changes but didn't finish
                modified = result.files_changed
                log_warning(f"Agent did not complete but modified {len(modified)} file(s): {result.summary}")
            else:
                log_error(f"Agent did not complete: {result.summary}")
                return 1
    else:
        # ---------------------------------------------------------------
        # STANDARD MODE: one-shot generation + external test/retry loop
        # ---------------------------------------------------------------
        for attempt in range(max_retries + 1):
            if attempt == 0:
                with spinner("Generating changes with AI"):
                    changes = generate_changes(
                        requirements,
                        context,
                        llm_config=ai_cfg,
                        verbose=ai_cfg.get("verbose", False),
                        reference_pr_content=reference_pr_content,
                        framework_context=framework_context,
                        testing_strategy=testing_strategy,
                        build_tool=build_tool,
                        full_config=config,
                    )
            else:
                with spinner(f"Regenerating (attempt {attempt + 1}/{max_retries + 1}) after test failure"):
                    changes = regenerate_with_error_analysis(
                        requirements,
                        context,
                        error_output=error_output,
                        previous_changes=changes or [],
                        llm_config=ai_cfg,
                        verbose=ai_cfg.get("verbose", False),
                        reference_pr_content=reference_pr_content,
                        framework_context=framework_context,
                        testing_strategy=testing_strategy,
                        build_tool=build_tool,
                        full_config=config,
                    )

            if not changes:
                log_error("No changes generated. Check requirements and codebase context.")
                return 1

            log_success(f"Generated {len(changes)} file change(s)")
            with step("Applying changes", ", ".join(c.get("path", "?") for c in changes[:5])):
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
            context = build_context(
                str(clone_path),
                requirements=requirements,
                config=config,
                grep_patterns=grep_patterns,
            )
            consciousness = build_or_load_consciousness(str(clone_path), config, repo_url=repo_url)
            consciousness_str = consciousness.to_context_string()
            if consciousness_str:
                context += f"\n\n{consciousness_str}"
            if repo_knowledge:
                context += repo_knowledge

    if args.dry_run or using_local_repo:
        if using_local_repo:
            log_success(f"Local repo mode complete. Changes applied to {clone_path}")
        else:
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
