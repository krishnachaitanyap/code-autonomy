"""
JIRA run service — orchestrates JIRA-to-PR generation runs with live progress tracking.

Follows the same _progress()/_log_event() pattern as TestingService.execute_run().
"""

import io
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.data.database import get_session
from src.data.models import JiraRun, Repo

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


class JiraRunService:
    """Service for JIRA-to-PR run tracking and execution."""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_runs(
        self, *, repo_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> list[JiraRun]:
        with get_session() as db:
            q = db.query(JiraRun)
            if repo_id:
                q = q.filter(JiraRun.repo_id == repo_id)
            if status:
                q = q.filter(JiraRun.status == status)
            return q.order_by(JiraRun.created_at.desc()).limit(limit).all()

    def get_run(self, run_id: str) -> Optional[JiraRun]:
        with get_session() as db:
            return db.get(JiraRun, run_id)

    def create_run(
        self, *, repo_id: str, jira_project: str = "", config: Optional[dict] = None
    ) -> JiraRun:
        with get_session() as db:
            run = JiraRun(
                id=_uuid(),
                repo_id=repo_id,
                jira_project=jira_project,
                config=config or {},
            )
            db.add(run)
            db.flush()
            db.refresh(run)
            return run

    def cancel_run(self, run_id: str) -> Optional[JiraRun]:
        with get_session() as db:
            run = db.get(JiraRun, run_id)
            if run and run.status in ("queued", "running"):
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                db.flush()
            return run

    def retry_run(self, run_id: str) -> Optional[JiraRun]:
        with get_session() as db:
            run = db.get(JiraRun, run_id)
            if run and run.status in ("failed", "error", "cancelled"):
                run.status = "queued"
                run.progress_pct = 0.0
                run.log = []
                run.started_at = None
                run.completed_at = None
                run.total_stories = 0
                run.completed_stories = 0
                run.succeeded_stories = 0
                run.failed_stories = 0
                run.result_summary = ""
                run.artifacts = {}
                db.flush()
            return run

    # ------------------------------------------------------------------
    # Execution pipeline
    # ------------------------------------------------------------------

    def execute_run(
        self,
        run_id: str,
        config: dict,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Optional[JiraRun]:
        """Execute a queued JIRA run. Called from a background thread."""

        def _progress(pct: float, stage: str, detail: str = ""):
            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if run:
                    run.progress_pct = pct
                    log_entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": stage,
                        "detail": detail,
                        "progress": pct,
                    }
                    run.log = (run.log or []) + [log_entry]
                    db.flush()
            if progress_callback:
                progress_callback({"type": "progress", "run_id": run_id, "progress": pct, "stage": stage, "detail": detail})

        def _log_event(event_type: str, message: str):
            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if run:
                    log_entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": event_type,
                        "detail": message,
                        "progress": run.progress_pct,
                    }
                    run.log = (run.log or []) + [log_entry]
                    db.flush()

        def _update_counts(succeeded: int, failed: int, completed: int, total: int):
            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if run:
                    run.succeeded_stories = succeeded
                    run.failed_stories = failed
                    run.completed_stories = completed
                    run.total_stories = total
                    db.flush()

        try:
            # --- A. Initialize ---
            _progress(5, "initializing", "Loading run configuration")
            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if not run:
                    logger.error("JiraRun %s not found", run_id)
                    return None
                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
                run.agent_id = f"jira-worker-{_uuid()[:8]}"
                repo_id = run.repo_id
                jira_project = run.jira_project
                db.flush()

            # Resolve repo
            with get_session() as db:
                repo = db.get(Repo, repo_id)
                repo_path = repo.local_path if repo else ""
                repo_url = repo.url if repo else ""

            if not repo_path or not Path(repo_path).is_dir():
                # Auto-clone if repo has a URL
                try:
                    from src.services.repo_service import RepoService
                    _log_event("initializing", "Repository path not found locally, auto-cloning...")
                    repo_path = RepoService().ensure_local_clone(
                        repo_id, branch="main", config=config,
                    )
                    _log_event("initializing", f"Clone complete: {repo_path}")
                except Exception as clone_exc:
                    _log_event("error", f"Repository path not found and auto-clone failed: {clone_exc}")
                    with get_session() as db:
                        run = db.get(JiraRun, run_id)
                        if run:
                            run.status = "error"
                            run.completed_at = datetime.now(timezone.utc)
                            run.result_summary = f"Repository path not found: {clone_exc}"
                            db.flush()
                    return None

            _log_event("initializing", f"Repository: {repo_path}")

            # Load config sections
            jira_cfg = config.get("jira") or {}
            ai_cfg = config.get("ai") or {}
            agent_cfg_section = config.get("agent") or {}
            bb_cfg = config.get("bitbucket") or {}
            bb_enabled = bb_cfg.get("enabled", False)

            if not jira_cfg.get("base_url"):
                _log_event("error", "Missing [jira] section in config — cannot connect to JIRA")
                with get_session() as db:
                    run = db.get(JiraRun, run_id)
                    if run:
                        run.status = "error"
                        run.completed_at = datetime.now(timezone.utc)
                        run.result_summary = "Missing JIRA configuration"
                        db.flush()
                return None

            # --- B. Authenticate ---
            _progress(10, "authenticating", "Authenticating to JIRA")
            from src.jira.client import (
                add_jira_comment,
                fetch_agent_stories,
                get_jira_token,
                transition_jira_issue,
            )
            try:
                token = get_jira_token(config)
                _log_event("authenticating", "JIRA authentication successful")
            except Exception as e:
                _log_event("error", f"JIRA authentication failed: {e}")
                with get_session() as db:
                    run = db.get(JiraRun, run_id)
                    if run:
                        run.status = "error"
                        run.completed_at = datetime.now(timezone.utc)
                        run.result_summary = f"Auth failed: {e}"
                        db.flush()
                return None

            # --- C. Fetch stories ---
            _progress(15, "fetching_stories", "Fetching stories from JIRA")
            try:
                stories = fetch_agent_stories(config, token=token)
            except Exception as e:
                _log_event("error", f"Failed to fetch stories: {e}")
                with get_session() as db:
                    run = db.get(JiraRun, run_id)
                    if run:
                        run.status = "error"
                        run.completed_at = datetime.now(timezone.utc)
                        run.result_summary = f"Fetch failed: {e}"
                        db.flush()
                return None

            if not stories:
                _log_event("fetching_stories", "No stories found matching agent label")
                with get_session() as db:
                    run = db.get(JiraRun, run_id)
                    if run:
                        run.status = "completed"
                        run.completed_at = datetime.now(timezone.utc)
                        run.result_summary = "No stories found"
                        run.progress_pct = 100.0
                        db.flush()
                return None

            total = len(stories)
            _log_event("discovery_result", f"Found {total} stories to process")
            for s in stories[:5]:
                _log_event("discovery_result", f"  {s['key']}: {s['summary'][:60]}")
            if total > 5:
                _log_event("discovery_result", f"  ... and {total - 5} more")
            _update_counts(0, 0, 0, total)

            # --- D. Analyze codebase ---
            _progress(20, "analyzing_codebase", "Building repository context")
            from src.agent.analyzer import generate_changes_with_agent
            from src.agent.knowledge import compute_repo_id, load_repo_knowledge
            from src.code.executor import detect_build_tool
            from src.consciousness.core import build_or_load_consciousness

            consciousness = build_or_load_consciousness(repo_path, config, repo_url=repo_url)
            _log_event("analyzing_codebase", "Repository consciousness loaded")

            code_index = None
            try:
                from src.code_index import build_or_load_code_index
                code_index = build_or_load_code_index(
                    repo_path, config, repo_url=repo_url, consciousness=consciousness
                )
                sym = getattr(code_index, "total_symbols", 0)
                files = getattr(code_index, "total_files", 0)
                _log_event("discovery_result", f"Code index: {sym} symbols in {files} files")
            except Exception:
                _log_event("analyzing_codebase", "Code index skipped (optional)")

            repo_knowledge = load_repo_knowledge(repo_path)
            build_tool = detect_build_tool(repo_path)

            # Agent config
            agent_config = {
                "max_turns": int(agent_cfg_section.get("max_turns", 50)),
                "smart_summarization": agent_cfg_section.get("smart_summarization", True),
                "truncation_limit": int(agent_cfg_section.get("truncation_limit", 30000)),
                "skip_tests": False,
            }

            # Resolve API key
            api_key = (ai_cfg.get("api_key") or "").strip()
            if not api_key:
                provider = (ai_cfg.get("provider") or "openai").lower()
                env_var = ai_cfg.get("api_key_env") or {
                    "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY",
                    "gemini": "GEMINI_API_KEY",
                }.get(provider, "OPENAI_API_KEY")
                api_key = os.environ.get(env_var, "")
            if not api_key:
                _log_event("error", "No LLM API key configured")
                with get_session() as db:
                    run = db.get(JiraRun, run_id)
                    if run:
                        run.status = "error"
                        run.completed_at = datetime.now(timezone.utc)
                        run.result_summary = "No API key"
                        db.flush()
                return None

            # --- E. Process each story ---
            succeeded = 0
            failed = 0
            completed = 0
            story_results = []
            accumulated_wm: dict[str, str] = {}

            for i, story in enumerate(stories, 1):
                key = story["key"]
                summary = story["summary"][:80]
                base_pct = 20 + (i - 1) * (70 / total)
                next_pct = 20 + i * (70 / total)

                _progress(base_pct, "processing_story", f"[{i}/{total}] {key}: {summary}")
                _log_event("story_start", f"Starting {key}: {summary}")

                # Build requirements from story
                requirements = self._build_requirements(story)

                # Detect JISI BDD
                self._detect_jisi_bdd(requirements, story, config)

                # JIRA transition to In Progress
                if jira_cfg.get("auto_transition_start"):
                    try:
                        transition_jira_issue(config, key, "In Progress", token=token)
                        _log_event("story_start", f"Transitioned {key} to In Progress")
                    except Exception:
                        pass

                # Bitbucket branch (optional)
                story_branch = ""
                if bb_enabled:
                    story_branch = self._create_branch(bb_cfg, repo_path, key)
                    if story_branch:
                        _log_event("story_branch", f"Created branch: {story_branch}")
                    else:
                        _log_event("story_error", f"{key}: Branch creation failed")

                # Run agent with StdoutTee
                _log_event("generating_tests", f"Invoking agent for {key}...")
                result = self._run_agent_with_capture(
                    requirements=requirements,
                    repo_path=repo_path,
                    ai_cfg=ai_cfg,
                    agent_config=agent_config,
                    consciousness=consciousness,
                    code_index=code_index,
                    repo_url=repo_url,
                    repo_knowledge=repo_knowledge,
                    config=config,
                    build_tool=build_tool,
                    log_fn=_log_event,
                    accumulated_wm=accumulated_wm,
                )

                if result and result.success:
                    files_count = len(result.files_changed) if result.files_changed else 0
                    _log_event("story_success", f"{key}: {files_count} file(s) modified")

                    # Accumulate working memory
                    if result.working_memory:
                        accumulated_wm.update(result.working_memory)

                    # Bitbucket: commit + PR
                    pr_url = ""
                    if bb_enabled and story_branch:
                        pr_url = self._commit_and_pr(
                            bb_cfg, repo_path, story_branch, key, story, result, repo_url
                        )
                        if pr_url:
                            _log_event("story_pr", f"{key}: PR created -> {pr_url}")

                    # JIRA comment + transition
                    self._post_success_comment(config, key, result, pr_url, token, add_jira_comment)
                    if jira_cfg.get("auto_transition_done"):
                        try:
                            transition_jira_issue(config, key, "Done", token=token)
                        except Exception:
                            pass

                    succeeded += 1
                    story_results.append({
                        "key": key, "summary": story["summary"],
                        "status": "success", "files_changed": files_count, "pr_url": pr_url,
                    })
                else:
                    error_msg = result.summary if result else "Agent crashed"
                    _log_event("story_error", f"{key}: {error_msg}")

                    # Discard branch on failure
                    if bb_enabled:
                        self._discard_branch(bb_cfg, repo_path)

                    # JIRA failure comment
                    self._post_failure_comment(config, key, error_msg, token, add_jira_comment)

                    failed += 1
                    story_results.append({
                        "key": key, "summary": story["summary"],
                        "status": "failed", "files_changed": 0, "pr_url": "",
                    })

                completed += 1
                _update_counts(succeeded, failed, completed, total)
                _progress(next_pct, "processing_story", f"Completed {key}")

            # --- F. Finalize ---
            _progress(95, "finalizing", "JIRA processing complete")

            final_status = "completed" if failed == 0 else "failed"
            summary = f"{succeeded}/{total} stories succeeded"
            if failed:
                summary += f", {failed} failed"

            _progress(100, "complete", summary)

            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if run:
                    run.status = final_status
                    run.completed_at = datetime.now(timezone.utc)
                    run.result_summary = summary
                    run.artifacts = {"stories": story_results}
                    db.flush()
                    return run

        except Exception as exc:
            logger.error("JiraRun %s failed: %s", run_id, exc, exc_info=True)
            _log_event("error", f"Run failed: {exc}")
            with get_session() as db:
                run = db.get(JiraRun, run_id)
                if run:
                    run.status = "error"
                    run.completed_at = datetime.now(timezone.utc)
                    run.result_summary = str(exc)
                    db.flush()
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_requirements(self, story: dict) -> str:
        parts = [f"# {story['key']}: {story['summary']}"]
        if story.get("description"):
            parts.append(f"\n## Description\n{story['description']}")
        if story.get("acceptance_criteria"):
            parts.append(f"\n## Acceptance Criteria\n{story['acceptance_criteria']}")
        return "\n".join(parts)

    def _detect_jisi_bdd(self, requirements: str, story: dict, config: dict):
        import json
        req_lower = requirements.lower()
        if any(kw in req_lower for kw in ["jisi_bdd", "jisi bdd", "commonsteps", "servicebase"]):
            if "bdd_spec" not in config:
                desc = story.get("description", "")
                try:
                    json_match = re.search(r'\{[^{}]*"service_name"[^{}]*\}', desc, re.DOTALL) if desc else None
                    if json_match:
                        import json
                        from src.bdd.service_spec import ServiceSpec
                        spec = ServiceSpec.from_dict(json.loads(json_match.group(0)))
                        config["bdd_spec"] = spec
                except Exception:
                    pass

    def _run_agent_with_capture(
        self, *, requirements, repo_path, ai_cfg, agent_config,
        consciousness, code_index, repo_url, repo_knowledge,
        config, build_tool, log_fn, accumulated_wm,
    ):
        """Run agent with StdoutTee to capture tool calls."""
        from src.agent.analyzer import generate_changes_with_agent

        original_stdout = sys.stdout
        my_thread_id = threading.current_thread().ident
        tool_call_pattern = re.compile(r'^\s*[\u25b8\u25b8]\s+(\S+)\s+(.+)')

        class StdoutTee(io.TextIOBase):
            def write(self, text):
                original_stdout.write(text)
                if threading.current_thread().ident != my_thread_id:
                    return len(text)
                for line in text.splitlines():
                    stripped = line.strip()
                    match = tool_call_pattern.match(stripped)
                    if match:
                        log_fn("tool_call", stripped.lstrip('\u25b8\u25b8 '))
                    elif '[agent] LLM API error' in stripped or '[agent] Aborting' in stripped:
                        msg = stripped.replace('[agent]', '').strip()
                        log_fn("error", msg)
                return len(text)

            def flush(self):
                original_stdout.flush()

        sys.stdout = StdoutTee()
        try:
            result = generate_changes_with_agent(
                requirements, repo_path,
                llm_config=ai_cfg,
                verbose=ai_cfg.get("verbose", False),
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
                initial_working_memory=accumulated_wm or None,
            )
            return result
        except Exception as exc:
            log_fn("error", f"Agent crashed: {exc}")
            return None
        finally:
            sys.stdout = original_stdout

    def _create_branch(self, bb_cfg: dict, repo_path: str, key: str) -> str:
        """Create a feature branch for a story. Returns branch name or empty string."""
        try:
            from src.jira.bitbucket_bridge import clone_and_prepare_branch
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_key = re.sub(r"[^\w\-]", "-", key.strip()).strip("-")
            story_branch = f"feature/auto-{safe_key}-{ts}"
            bb_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
            result_dir = clone_and_prepare_branch(
                bb_cfg.get("clone_url", ""),
                branch_name=story_branch,
                from_branch=bb_cfg.get("base_branch", "main"),
                target_dir=repo_path,
                auth_token=bb_token,
                protocol=bb_cfg.get("clone_protocol", "ssh"),
            )
            return story_branch if result_dir else ""
        except Exception:
            return ""

    def _commit_and_pr(self, bb_cfg, repo_path, story_branch, key, story, result, repo_url) -> str:
        """Commit changes and create PR. Returns PR URL or empty string."""
        try:
            from src.jira.bitbucket_bridge import commit_and_push, create_story_pr
            bb_token = bb_cfg.get("user_token", "") if bb_cfg.get("clone_protocol", "ssh") == "https" else None
            pushed = commit_and_push(
                repo_path, story_branch,
                commit_msg=f"{key}: {result.summary}", auth_token=bb_token,
            )
            if pushed:
                pr_url = create_story_pr(
                    bb_cfg, repo_url, story_branch,
                    bb_cfg.get("base_branch", "main"),
                    key, story["summary"], result.summary,
                ) or ""
                return pr_url
        except Exception:
            pass
        return ""

    def _discard_branch(self, bb_cfg: dict, repo_path: str):
        try:
            from src.jira.bitbucket_bridge import discard_story_changes
            discard_story_changes(repo_path, bb_cfg.get("base_branch", "main"))
        except Exception:
            pass

    def _post_success_comment(self, config, key, result, pr_url, token, add_jira_comment):
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

    def _post_failure_comment(self, config, key, error_msg, token, add_jira_comment):
        try:
            from src.jira.client import add_jira_comment
            comment = f"[code-autonomy] Agent did not complete.\nError: {error_msg}"
            add_jira_comment(config, key, comment, token=token)
        except Exception:
            pass
