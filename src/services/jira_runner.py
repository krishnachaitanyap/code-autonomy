"""
JIRA runner — extracted from main.py for the multi-story JIRA processing loop.

This module contains the full JIRA mode orchestration logic including
Bitbucket Server integration, per-story branch management, and retry logic.
"""

import os
import re
from pathlib import Path
from typing import Any

from src.agent.activity import (
    header,
    log_error,
    log_info,
    log_success,
    log_warning,
    spinner,
    step,
)
from src.agent.knowledge import compute_repo_id, load_repo_knowledge
from src.config_loader import load_config
from src.consciousness.core import build_or_load_consciousness
from src.llm_client import configure_resiliency


def _build_requirements_from_story(story: dict) -> str:
    """Convert a JIRA story dict into an agent requirements string."""
    parts = [f"# {story['key']}: {story['summary']}"]
    if story.get("description"):
        parts.append(f"\n## Description\n{story['description']}")
    if story.get("acceptance_criteria"):
        parts.append(f"\n## Acceptance Criteria\n{story['acceptance_criteria']}")
    return "\n".join(parts)


def run_jira_mode(args: Any) -> int:
    """Pull stories from JIRA and process each with the agent.

    This is the full JIRA orchestration loop extracted from main.py.
    """
    from src.agent.analyzer import generate_changes_with_agent
    from src.jira.client import (
        add_jira_comment,
        fetch_agent_stories,
        get_jira_token,
        transition_jira_issue,
    )
    from src.jira.session import (
        STATUS_FAILED,
        STATUS_IN_PROGRESS,
        STATUS_PENDING,
        STATUS_SUCCESS,
        JiraSession,
        clear_jira_session,
        create_jira_session,
        load_jira_session,
        save_jira_session,
    )
    from src.startup_validator import validate_startup

    project_root = Path(__file__).parent.parent.parent
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
    bb_repo_dir: str = ""
    bb_clone_url: str = bb_cfg.get("clone_url", "") if bb_enabled else ""

    # Resolve repo path
    clone_path = _resolve_clone_path(args, config, bb_enabled, bb_cfg, bb_clone_url)
    if clone_path is None:
        return 1

    if bb_enabled and not bb_repo_dir:
        bb_repo_dir = str(clone_path)

    if bb_enabled and not bb_clone_url:
        bb_clone_url = _derive_bb_clone_url(bb_cfg)

    # Detect repo_url from git remote
    repo_url = _detect_repo_url(clone_path)

    header("JIRA Mode", f"Repo: {clone_path}" + (" (Bitbucket Server)" if bb_enabled else ""))

    # Pre-flight validation
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

    repo_id = compute_repo_id(str(clone_path), repo_url)

    # Resume or fresh start
    resume_mode = getattr(args, "resume", False)
    session, stories, accumulated_wm = _resolve_session(
        resume_mode, repo_id, config, token, fetch_agent_stories, load_jira_session,
        create_jira_session, save_jira_session, clear_jira_session,
    )
    if stories is None:
        return 0  # Nothing to do

    # Build consciousness and code index once
    with step("Analyzing codebase"):
        consciousness = build_or_load_consciousness(str(clone_path), config, repo_url=repo_url)
        log_info("Loaded project consciousness")

        code_index = None
        try:
            from src.code_index import build_or_load_code_index
            code_index = build_or_load_code_index(
                str(clone_path), config, repo_url=repo_url, consciousness=consciousness
            )
            log_info(f"Loaded code index ({code_index.total_symbols} symbols)")
        except Exception as _ci_err:
            log_warning(f"Could not build code index: {_ci_err}")

        repo_knowledge = load_repo_knowledge(str(clone_path))

    # Agent config
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

    # Collect prior results
    results: list[dict] = []
    if resume_mode and session:
        for s in session.succeeded_stories():
            results.append({"key": s.key, "status": "success", "files": s.files_changed, "resumed": True})

    # Process each story
    for i, story in enumerate(stories, 1):
        key = story["key"]
        log_info(f"\n[{i}/{len(stories)}] Processing {key}: {story['summary']}")

        if session:
            session.mark_story(key, STATUS_IN_PROGRESS)
            save_jira_session(session)

        requirements = _build_requirements_from_story(story)

        # Detect JISI BDD from story content
        _detect_jisi_bdd(requirements, story, config)

        # JIRA transitions
        if jira_cfg.get("auto_transition_start"):
            try:
                transition_jira_issue(config, key, "In Progress", token=token)
                log_info(f"  Transitioned {key} → In Progress")
            except Exception as te:
                log_warning(f"  Could not transition {key}: {te}")

        # Create feature branch for this story (Bitbucket)
        story_branch = ""
        if bb_enabled and bb_repo_dir:
            story_branch = _create_story_branch(
                bb_clone_url, bb_cfg, bb_repo_dir, key, session, save_jira_session, results
            )
            if story_branch is None:
                continue

        # Run agent with retry
        story_was_in_progress = (
            resume_mode and session and
            session.get_story(key) and
            session.get_story(key).status == STATUS_IN_PROGRESS
        )

        max_retries = int(jira_cfg.get("max_retries", 2))
        result = _run_story_agent(
            key, story, requirements, clone_path, ai_cfg, agent_config,
            consciousness, code_index, repo_url, repo_knowledge, config,
            accumulated_wm, max_retries, story_was_in_progress,
            bb_enabled, bb_repo_dir, bb_cfg, session, save_jira_session
        )

        if result is None:
            results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})
            continue

        # Accumulate working memory
        if result.working_memory:
            accumulated_wm.update(result.working_memory)

        if result.success:
            _handle_story_success(
                key, story, result, session, save_jira_session,
                bb_enabled, bb_repo_dir, bb_cfg, story_branch, repo_url,
                config, jira_cfg, token, results, add_jira_comment, transition_jira_issue
            )
        else:
            _handle_story_failure(
                key, result, session, save_jira_session,
                bb_enabled, bb_repo_dir, bb_cfg,
                config, token, results, add_jira_comment
            )

    # Finalize session
    if session:
        if session.all_succeeded():
            clear_jira_session(repo_id)
        else:
            save_jira_session(session)
            failed_count = len([r for r in results if r["status"] == "failed"])
            if failed_count:
                log_info(f"Session saved — {failed_count} story(ies) failed. Run with --jira --resume to retry.")

    # Summary
    _print_summary(results)

    failed = sum(1 for r in results if r["status"] == "failed")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Helper functions (extracted from the monolithic loop)
# ---------------------------------------------------------------------------

def _resolve_clone_path(args, config, bb_enabled, bb_cfg, bb_clone_url):
    """Resolve the clone path based on args and config."""
    if bb_enabled and not args.repo_path:
        from src.jira.bitbucket_bridge import clone_and_prepare_branch
        if not bb_clone_url:
            bb_clone_url = _derive_bb_clone_url(bb_cfg)
        work_dir = Path(config.get("workflow", {}).get("work_dir", "./workspace")).resolve()
        target_dir = work_dir / f"jira-{bb_cfg.get('repo_slug', 'repo')}"
        with spinner("Cloning from Bitbucket Server"):
            base = bb_cfg.get("base_branch", "main")
            bb_repo_dir = clone_and_prepare_branch(
                bb_clone_url, branch_name=base, from_branch=base,
                target_dir=str(target_dir),
                auth_token=bb_cfg.get("user_token", ""),
                protocol=bb_cfg.get("clone_protocol", "ssh"),
            )
            if bb_repo_dir is None:
                log_error("Bitbucket clone failed")
                return None
            return Path(bb_repo_dir).resolve()
    elif args.repo_path:
        clone_path = Path(args.repo_path).resolve()
        if not clone_path.is_dir():
            log_error(f"Repo path is not a directory: {clone_path}")
            return None
        return clone_path
    else:
        log_error("--repo-path is required when using --jira mode (unless [bitbucket] is enabled)")
        return None


def _derive_bb_clone_url(bb_cfg):
    """Derive clone URL from Bitbucket config."""
    from urllib.parse import urlparse
    parsed = urlparse(bb_cfg["base_url"].rstrip("/"))
    bb_origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        bb_origin += f":{parsed.port}"
    pkey = bb_cfg["project_key"]
    rslug = bb_cfg["repo_slug"]
    if bb_cfg.get("clone_protocol", "ssh") == "ssh":
        return f"ssh://git@{parsed.hostname}:7999/{pkey}/{rslug}.git"
    return f"{bb_origin}/scm/{pkey}/{rslug}.git"


def _detect_repo_url(clone_path):
    """Detect repo_url from git remote."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(clone_path), capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _resolve_session(
    resume_mode, repo_id, config, token,
    fetch_agent_stories, load_jira_session,
    create_jira_session, save_jira_session, clear_jira_session,
):
    """Resolve JIRA session (resume or create fresh). Returns (session, stories, accumulated_wm)."""
    accumulated_wm: dict[str, str] = {}
    session = None
    stories = None

    if resume_mode:
        session = load_jira_session(repo_id)
        if session and session.resumable_stories():
            succeeded = session.succeeded_stories()
            resumable = session.resumable_stories()
            failed_count = sum(1 for s in resumable if s.status == "failed")
            log_info(
                f"Resuming JIRA session: {len(succeeded)} succeeded, "
                f"{len(resumable)} remaining"
                + (f" ({failed_count} previously failed)" if failed_count else "")
            )
            for s in resumable:
                if s.status == "failed":
                    s.status = "pending"
                    s.error = ""
            save_jira_session(session)
            for s in session.stories:
                if s.working_memory:
                    accumulated_wm.update(s.working_memory)
            resumable_keys = {s.key for s in resumable}
            with spinner("Fetching stories from JIRA"):
                all_stories = fetch_agent_stories(config, token=token)
            stories = [s for s in all_stories if s["key"] in resumable_keys]
            if not stories:
                log_info("No resumable stories found in JIRA. Session complete.")
                clear_jira_session(repo_id)
                return session, None, accumulated_wm
        else:
            log_info("No resumable JIRA session found — starting fresh")
            resume_mode = False

    if not resume_mode or stories is None:
        with spinner("Fetching stories from JIRA"):
            stories = fetch_agent_stories(config, token=token)
        if not stories:
            log_info("No stories found matching the agent label. Nothing to do.")
            return None, None, accumulated_wm
        log_info(f"Found {len(stories)} story(ies) to process")
        session = create_jira_session(repo_id, stories)
        save_jira_session(session)

    return session, stories, accumulated_wm


def _detect_jisi_bdd(requirements, story, config):
    """Detect JISI BDD spec embedded in story."""
    import json
    req_lower = requirements.lower()
    if any(kw in req_lower for kw in ["jisi_bdd", "jisi bdd", "commonsteps", "servicebase"]):
        if "bdd_spec" not in config:
            desc = story.get("description", "")
            try:
                json_match = re.search(r'\{[^{}]*"service_name"[^{}]*\}', desc, re.DOTALL) if desc else None
                if json_match:
                    from src.bdd.service_spec import ServiceSpec
                    spec = ServiceSpec.from_dict(json.loads(json_match.group(0)))
                    config["bdd_spec"] = spec
                    log_info(f"  Detected JISI BDD spec from story: {spec.service_name}")
            except Exception:
                pass


def _create_story_branch(bb_clone_url, bb_cfg, bb_repo_dir, key, session, save_jira_session, results):
    """Create a feature branch for a story. Returns branch name or None on failure."""
    from datetime import datetime
    from src.jira.bitbucket_bridge import clone_and_prepare_branch
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_key = re.sub(r"[^\w\-]", "-", key.strip()).strip("-")
    story_branch = f"feature/auto-{safe_key}-{ts}"
    bb_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
    result_dir = clone_and_prepare_branch(
        bb_clone_url, branch_name=story_branch,
        from_branch=bb_cfg.get("base_branch", "main"),
        target_dir=bb_repo_dir, auth_token=bb_token,
        protocol=bb_cfg.get("clone_protocol", "ssh"),
    )
    if result_dir is None:
        log_error(f"  {key}: Could not create branch {story_branch}")
        results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})
        if session:
            session.mark_story(key, "failed", error="branch creation failed")
            save_jira_session(session)
        return None
    log_info(f"  Created branch: {story_branch}")
    return story_branch


def _run_story_agent(
    key, story, requirements, clone_path, ai_cfg, agent_config,
    consciousness, code_index, repo_url, repo_knowledge, config,
    accumulated_wm, max_retries, story_was_in_progress,
    bb_enabled, bb_repo_dir, bb_cfg, session, save_jira_session,
):
    """Run agent for a single story with retry logic. Returns result or None on crash."""
    from src.agent.analyzer import generate_changes_with_agent
    try:
        result = None
        for attempt in range(1, max_retries + 1):
            is_resume = attempt > 1 or (attempt == 1 and story_was_in_progress)
            with spinner(f"Agent {'resuming' if is_resume else 'working on'} {key}" +
                        (f" (attempt {attempt}/{max_retries})" if attempt > 1 else "")):
                result = generate_changes_with_agent(
                    requirements, str(clone_path),
                    llm_config=ai_cfg, verbose=ai_cfg.get("verbose", False),
                    consciousness=consciousness, agent_config=agent_config,
                    config=config, repo_url=repo_url,
                    repo_knowledge=repo_knowledge, code_index=code_index,
                    resume=is_resume,
                    initial_working_memory=accumulated_wm or None,
                )
            if result.success:
                break
            if result.checkpoint and result.files_changed and attempt < max_retries:
                log_warning(f"  {key}: Agent ran out of turns ({len(result.files_changed)} file(s) so far) — resuming...")
            else:
                break
        return result
    except Exception as exc:
        log_error(f"  {key}: Agent crashed — {exc}")
        if bb_enabled and bb_repo_dir:
            from src.jira.bitbucket_bridge import discard_story_changes
            discard_story_changes(bb_repo_dir, bb_cfg.get("base_branch", "main"))
        if session:
            session.mark_story(key, "failed", error=f"crash: {exc}")
            save_jira_session(session)
        return None


def _handle_story_success(
    key, story, result, session, save_jira_session,
    bb_enabled, bb_repo_dir, bb_cfg, story_branch, repo_url,
    config, jira_cfg, token, results, add_jira_comment, transition_jira_issue,
):
    """Handle a successful story result."""
    log_success(f"  {key}: Agent completed — {len(result.files_changed)} file(s) modified")

    pr_url = ""
    if bb_enabled and bb_repo_dir and story_branch:
        from src.jira.bitbucket_bridge import commit_and_push, create_story_pr
        bb_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
        pushed = commit_and_push(
            bb_repo_dir, story_branch,
            commit_msg=f"{key}: {result.summary}", auth_token=bb_token,
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

    if session:
        session.mark_story(key, "success", files_changed=len(result.files_changed))
        story_state = session.get_story(key)
        if story_state and result.working_memory:
            story_state.working_memory = result.working_memory
        save_jira_session(session)

    comment = (
        f"[code-autonomy] Agent completed successfully.\n"
        f"Files modified: {', '.join(result.files_changed) or 'none'}\n"
        f"Summary: {result.summary}"
    )
    if pr_url:
        comment += f"\nPull Request: {pr_url}"
    try:
        add_jira_comment(config, key, comment, token=token)
    except Exception:
        pass

    if jira_cfg.get("auto_transition_done"):
        try:
            transition_jira_issue(config, key, "Done", token=token)
        except Exception:
            pass

    results.append({"key": key, "status": "success", "files": len(result.files_changed), "pr_url": pr_url})


def _handle_story_failure(
    key, result, session, save_jira_session,
    bb_enabled, bb_repo_dir, bb_cfg,
    config, token, results, add_jira_comment,
):
    """Handle a failed story result."""
    log_error(f"  {key}: Agent did not complete — {result.summary}")

    if bb_enabled and bb_repo_dir:
        from src.jira.bitbucket_bridge import discard_story_changes
        discard_story_changes(bb_repo_dir, bb_cfg.get("base_branch", "main"))

    if session:
        session.mark_story(key, "failed", error=result.summary)
        story_state = session.get_story(key)
        if story_state and result.working_memory:
            story_state.working_memory = result.working_memory
        save_jira_session(session)

    comment = f"[code-autonomy] Agent did not complete.\nError: {result.summary}"
    try:
        add_jira_comment(config, key, comment, token=token)
    except Exception:
        pass

    results.append({"key": key, "status": "failed", "files": 0, "pr_url": ""})


def _print_summary(results):
    """Print JIRA processing summary."""
    print(f"\n{'=' * 60}")
    print("JIRA Processing Summary")
    print(f"{'=' * 60}")
    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"  Total: {len(results)}  |  Succeeded: {succeeded}  |  Failed: {failed}")
    print(f"{'─' * 60}")
    for r in results:
        icon = "OK" if r["status"] == "success" else "FAIL"
        pr_info = f"  PR: {r.get('pr_url', '')}" if r.get("pr_url") else ""
        print(f"  [{icon}] {r['key']}  ({r.get('files', 0)} files){pr_info}")
    print(f"{'=' * 60}\n")
