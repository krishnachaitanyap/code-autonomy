"""
OrchestratorService — goal-driven workflow orchestration.

Decomposes a high-level user goal into ordered subtasks using an LLM,
then executes them sequentially with pause-at-checkpoint support.
"""

import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.data.database import get_session
from src.data.models import TestProject, Workflow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Cascading — tier mapping per provider
# ---------------------------------------------------------------------------

MODEL_TIERS: dict[str, dict[str, str]] = {
    "openai": {
        "fast": "gpt-4o-mini",
        "default": "gpt-4o",
    },
    "anthropic": {
        "fast": "claude-3-5-haiku-20241022",
        "default": "claude-sonnet-4-5-20250514",
    },
    "gemini": {
        "fast": "gemini-2.0-flash",
        "default": "gemini-1.5-pro",
    },
    "google": {
        "fast": "gemini-2.0-flash",
        "default": "gemini-1.5-pro",
    },
}

SUBTASK_TIER: dict[str, str] = {
    "discovery": "fast",
    "command": "fast",
    "coverage": "fast",
    "test": "fast",
    "agent": "default",
}

MAX_RETRIES = 2


def _get_tier_config(config: dict, tier: str) -> dict:
    """Return a config dict with the model overridden for the given tier."""
    ai_cfg = dict(config.get("ai", {}))
    provider = (ai_cfg.get("provider") or "openai").lower()
    provider_tiers = MODEL_TIERS.get(provider, {})
    if tier in provider_tiers:
        ai_cfg["model"] = provider_tiers[tier]
    return {**config, "ai": ai_cfg}


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubtaskResult:
    """Result from executing a single subtask."""
    success: bool = False
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    working_memory: dict[str, str] = field(default_factory=dict)
    error: str = ""


class OrchestratorService:
    """Orchestrates goal decomposition and multi-step workflow execution."""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_workflow(
        self,
        *,
        goal: str,
        mode: str = "testing",
        repo_id: str = "",
        project_id: str = "",
        config: dict | None = None,
        token_budget: int = 0,
    ) -> Workflow:
        workflow = Workflow(
            id=_uuid(),
            goal=goal,
            mode=mode,
            repo_id=repo_id or None,
            project_id=project_id or None,
            status="planning",
            config=config or {},
            token_budget=token_budget,
        )
        with get_session() as db:
            db.add(workflow)
            db.flush()
            db.expunge(workflow)
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        with get_session() as db:
            return db.get(Workflow, workflow_id)

    def list_workflows(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[Workflow]:
        with get_session() as db:
            q = db.query(Workflow)
            if status:
                q = q.filter(Workflow.status == status)
            return q.order_by(Workflow.created_at.desc()).limit(limit).all()

    def cancel_workflow(self, workflow_id: str) -> Optional[Workflow]:
        with get_session() as db:
            wf = db.get(Workflow, workflow_id)
            if not wf:
                return None
            if wf.status in ("completed", "cancelled"):
                return wf
            wf.status = "cancelled"
            wf.completed_at = datetime.now(timezone.utc)
            db.flush()
            db.expunge(wf)
        return wf

    # ------------------------------------------------------------------
    # Goal Decomposition (LLM-powered)
    # ------------------------------------------------------------------

    def decompose_goal(
        self,
        goal: str,
        mode: str,
        repo_context: dict,
        config: dict,
        usage_stats: Optional["LLMUsageStats"] = None,
        auto_advance: bool = False,
    ) -> list[dict]:
        """Use the LLM to decompose a goal into 3-8 ordered subtasks."""

        checkpoint_guidance = (
            "- Set checkpoint: false for ALL subtasks (auto-advance mode is enabled, the workflow will run without pausing)."
            if auto_advance
            else "- Use checkpoint sparingly — only set checkpoint: true for a single critical review point (e.g. after major code generation, before destructive operations). Most subtasks should have checkpoint: false."
        )

        system_prompt = f"""You are a senior software architect. Decompose the following goal into 3-8 concrete, ordered subtasks.

Each subtask must have:
- title: short name (5-10 words)
- description: specific instructions an AI coding agent can execute
- type: one of "discovery", "agent", "test", "coverage", "command"
- checkpoint: true if the user should review results before proceeding

Types:
- discovery: scan the repo for endpoints, services, patterns
- agent: generate/modify code using an AI coding agent
- test: execute tests (run mvn test / pytest)
- coverage: analyze test coverage
- command: run a shell command (build, lint, format)

Rules:
- Start with discovery/exploration when the goal requires understanding the codebase
{checkpoint_guidance}
- For testing goals: include test generation, execution, and coverage analysis
- For engineering goals: include implementation, testing, and verification

Output ONLY a JSON array of subtask objects. No markdown, no explanation."""

        user_msg_parts = [
            f"Goal: {goal}",
            f"Mode: {mode}",
        ]
        if repo_context.get("language"):
            user_msg_parts.append(f"Language: {repo_context['language']}")
        if repo_context.get("framework"):
            user_msg_parts.append(f"Framework: {repo_context['framework']}")
        if repo_context.get("endpoints"):
            endpoints = repo_context["endpoints"]
            ep_str = ", ".join(
                ep.get("file", "unknown") for ep in endpoints[:10]
            )
            user_msg_parts.append(f"Discovered endpoints ({len(endpoints)}): {ep_str}")
        if repo_context.get("services"):
            services = repo_context["services"]
            svc_str = ", ".join(
                svc.get("file", "unknown") for svc in services[:10]
            )
            user_msg_parts.append(f"Discovered services ({len(services)}): {svc_str}")

        user_msg = "\n".join(user_msg_parts)

        ai_cfg = config.get("ai", {})
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
            # Fallback: generate a reasonable default plan without LLM
            return self._default_subtasks(goal, mode)

        try:
            from src.llm_client import chat_completion

            # Use fast model for decomposition — it's a structured output task
            fast_config = _get_tier_config(config, "fast")
            fast_ai_cfg = fast_config.get("ai", ai_cfg)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]
            content, _ = chat_completion(
                messages,
                fast_ai_cfg,
                tools=None,
                tool_choice="none",
                temperature=0.3,
                full_config=fast_config,
                usage_stats=usage_stats,
                usage_category="decompose",
            )

            # Parse JSON from response
            subtasks = self._parse_subtasks_json(content)
            if subtasks:
                return subtasks
        except Exception as exc:
            logger.warning("LLM decomposition failed, using defaults: %s", exc)

        return self._default_subtasks(goal, mode)

    def _parse_subtasks_json(self, content: str) -> list[dict]:
        """Parse JSON subtasks from LLM response, handling markdown fences."""
        text = content.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    raw = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(raw, list):
            return []

        subtasks = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            subtasks.append({
                "index": i,
                "title": item.get("title", f"Step {i + 1}"),
                "description": item.get("description", ""),
                "type": item.get("type", "agent"),
                "status": "pending",
                "checkpoint": bool(item.get("checkpoint", False)),
                "requirements": "",
                "result_summary": "",
                "files_changed": [],
                "error": None,
                "started_at": None,
                "completed_at": None,
                "attempts": 1,
                "model_used": "",
                "tokens_used": 0,
            })

        return subtasks

    def _default_subtasks(self, goal: str, mode: str) -> list[dict]:
        """Generate sensible default subtasks when LLM is unavailable."""
        if mode == "testing":
            return [
                {
                    "index": 0, "title": "Discover endpoints and services",
                    "description": "Scan the repository for REST controllers, services, DTOs, and existing test files.",
                    "type": "discovery", "status": "pending", "checkpoint": False,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
                {
                    "index": 1, "title": "Generate tests",
                    "description": f"Generate tests to achieve the goal: {goal}",
                    "type": "agent", "status": "pending", "checkpoint": True,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
                {
                    "index": 2, "title": "Execute tests",
                    "description": "Run the generated tests and capture results.",
                    "type": "test", "status": "pending", "checkpoint": False,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
                {
                    "index": 3, "title": "Analyze coverage",
                    "description": "Analyze test coverage and identify remaining gaps.",
                    "type": "coverage", "status": "pending", "checkpoint": False,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
            ]
        else:  # engineering
            return [
                {
                    "index": 0, "title": "Explore codebase",
                    "description": "Scan the repository to understand the architecture and relevant files.",
                    "type": "discovery", "status": "pending", "checkpoint": False,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
                {
                    "index": 1, "title": "Implement changes",
                    "description": f"Implement the goal: {goal}",
                    "type": "agent", "status": "pending", "checkpoint": True,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
                {
                    "index": 2, "title": "Run tests",
                    "description": "Execute tests to verify the implementation.",
                    "type": "test", "status": "pending", "checkpoint": False,
                    "requirements": "", "result_summary": "", "files_changed": [],
                    "error": None, "started_at": None, "completed_at": None,
                    "attempts": 1, "model_used": "", "tokens_used": 0,
                },
            ]

    # ------------------------------------------------------------------
    # Workflow Execution
    # ------------------------------------------------------------------

    def execute_workflow(
        self,
        workflow_id: str,
        config: dict,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> None:
        """Execute a workflow's subtasks sequentially.

        Pauses at checkpoints and stops on failure.
        Called from a background thread.
        """

        def _emit(event_type: str, step: int, message: str, success: bool = True):
            log_entry = {
                "timestamp": _utcnow(),
                "event": event_type,
                "step": step,
                "message": message,
                "success": success,
            }
            with get_session() as db:
                wf = db.get(Workflow, workflow_id)
                if wf:
                    wf.log = (wf.log or []) + [log_entry]
                    db.flush()
            if progress_callback:
                progress_callback({"type": event_type, "workflow_id": workflow_id, **log_entry})

        def _save_workflow():
            pass  # changes are flushed in each _emit / update block

        try:
            from src.llm_client import LLMUsageStats

            # Load workflow
            with get_session() as db:
                wf = db.get(Workflow, workflow_id)
                if not wf:
                    logger.error("Workflow %s not found", workflow_id)
                    return
                subtasks = list(wf.subtasks or [])
                wf.status = "running"
                if not wf.started_at:
                    wf.started_at = datetime.now(timezone.utc)
                db.flush()

                # Snapshot for use outside session
                project_id = wf.project_id
                repo_id = wf.repo_id
                wf_config = dict(wf.config or {})
                goal = wf.goal
                mode = wf.mode
                token_budget = wf.token_budget or 0
                auto_advance = wf_config.get("auto_advance", False)

            if not subtasks:
                with get_session() as db:
                    wf = db.get(Workflow, workflow_id)
                    if wf:
                        wf.status = "completed"
                        wf.progress_pct = 100.0
                        wf.completed_at = datetime.now(timezone.utc)
                        wf.result_summary = "No subtasks to execute."
                        db.flush()
                return

            # Workflow-level token tracking
            workflow_usage = LLMUsageStats()

            # Resolve repo path from project
            repo_path = self._resolve_repo_path(project_id, repo_id)
            working_memory: dict[str, str] = {}
            budget_exceeded = False

            for i, subtask in enumerate(subtasks):
                if subtask.get("status") in ("completed", "skipped"):
                    continue  # already done (resume case)

                # Budget check — soft limit: won't start new subtask if budget exhausted
                if token_budget > 0 and workflow_usage.total_tokens >= token_budget:
                    subtask["status"] = "skipped"
                    subtask["error"] = f"Token budget exhausted ({workflow_usage.total_tokens}/{token_budget})"
                    _emit("budget_exceeded", i, f"Budget exhausted — skipping remaining subtasks")
                    budget_exceeded = True
                    break

                # Update state
                subtask["status"] = "running"
                subtask["started_at"] = _utcnow()
                _emit("subtask_start", i, subtask["title"])

                # Update progress
                progress = round((i / len(subtasks)) * 100, 1)
                with get_session() as db:
                    wf = db.get(Workflow, workflow_id)
                    if wf:
                        wf.current_step = i
                        wf.progress_pct = progress
                        wf.subtasks = subtasks
                        db.flush()

                # Retry loop with self-correction
                st_type = subtask.get("type", "agent")
                last_error: Optional[str] = None
                result = SubtaskResult(success=False, summary="No execution attempted")
                tokens_before = workflow_usage.total_tokens
                tier = SUBTASK_TIER.get(st_type, "default")
                tier_config = _get_tier_config(config, tier)

                for attempt in range(MAX_RETRIES + 1):
                    try:
                        tier = SUBTASK_TIER.get(st_type, "default")

                        # On second retry, escalate model tier
                        if attempt == 2 and tier == "fast":
                            tier = "default"

                        tier_config = _get_tier_config(config, tier)

                        # On retry, inject error context into requirements
                        exec_subtask = subtask
                        if attempt > 0 and last_error:
                            exec_subtask = dict(subtask)  # copy to avoid mutating original
                            original_req = exec_subtask.get("requirements") or exec_subtask.get("description", "")
                            exec_subtask["requirements"] = (
                                f"{original_req}\n\n"
                                f"PREVIOUS ATTEMPT FAILED (attempt {attempt}):\n{last_error}\n"
                                f"Please try a different approach to avoid this error."
                            )

                        # Execute based on type
                        if st_type == "discovery":
                            result = self._execute_discovery(project_id, exec_subtask, tier_config, repo_path)
                        elif st_type == "agent":
                            result = self._execute_agent(
                                exec_subtask, tier_config, repo_path, working_memory, goal, mode, wf_config
                            )
                            if result.working_memory:
                                working_memory.update(result.working_memory)
                        elif st_type == "test":
                            result = self._execute_tests(exec_subtask, tier_config, repo_path)
                        elif st_type == "coverage":
                            result = self._execute_coverage(project_id, exec_subtask)
                        elif st_type == "command":
                            result = self._execute_command(exec_subtask, repo_path)
                        else:
                            result = SubtaskResult(success=False, summary=f"Unknown type: {st_type}")

                        if result.success:
                            break  # Success — exit retry loop

                        last_error = result.error or result.summary

                    except Exception as exc:
                        logger.error("Subtask %d attempt %d failed: %s", i, attempt + 1, exc, exc_info=True)
                        last_error = str(exc)
                        result = SubtaskResult(success=False, summary=str(exc), error=str(exc))

                    if attempt < MAX_RETRIES:
                        _emit("retry", i, f"Retrying step {i} (attempt {attempt + 2}/{MAX_RETRIES + 1}): {last_error}")

                # Record result with retry + model metadata
                subtask["status"] = "completed" if result.success else "failed"
                subtask["result_summary"] = result.summary
                subtask["files_changed"] = result.files_changed
                subtask["completed_at"] = _utcnow()
                subtask["attempts"] = attempt + 1
                subtask["model_used"] = tier_config.get("ai", {}).get("model", "")
                if result.error:
                    subtask["error"] = result.error

                # Track tokens for this subtask
                tokens_this_step = workflow_usage.total_tokens - tokens_before
                subtask["tokens_used"] = tokens_this_step

                _emit("subtask_complete", i, subtask["title"], result.success)

                # Persist subtask state + running token total
                with get_session() as db:
                    wf = db.get(Workflow, workflow_id)
                    if wf:
                        wf.subtasks = subtasks
                        wf.total_tokens_used = workflow_usage.total_tokens
                        db.flush()

                # Checkpoint: pause for user review (skipped when auto_advance)
                if subtask.get("checkpoint") and result.success and i < len(subtasks) - 1 and not auto_advance:
                    with get_session() as db:
                        wf = db.get(Workflow, workflow_id)
                        if wf:
                            wf.status = "paused"
                            wf.current_step = i
                            wf.subtasks = subtasks
                            wf.progress_pct = round(((i + 1) / len(subtasks)) * 100, 1)
                            wf.total_tokens_used = workflow_usage.total_tokens
                            db.flush()
                    _emit("checkpoint", i, f"Paused for review after: {subtask['title']}")
                    return  # exit — user calls resume to continue

                # If failed after all retries, stop
                if subtask["status"] == "failed":
                    with get_session() as db:
                        wf = db.get(Workflow, workflow_id)
                        if wf:
                            wf.status = "failed"
                            wf.subtasks = subtasks
                            wf.result_summary = f"Failed at step {i}: {subtask['title']}"
                            wf.total_tokens_used = workflow_usage.total_tokens
                            wf.completed_at = datetime.now(timezone.utc)
                            db.flush()
                    return

            # All subtasks completed (or budget exceeded)
            with get_session() as db:
                wf = db.get(Workflow, workflow_id)
                if wf:
                    wf.status = "completed"
                    wf.progress_pct = 100.0
                    wf.subtasks = subtasks
                    wf.total_tokens_used = workflow_usage.total_tokens
                    wf.completed_at = datetime.now(timezone.utc)
                    # Build result summary from subtask summaries
                    summaries = [
                        f"Step {s['index'] + 1}: {s['result_summary']}"
                        for s in subtasks if s.get("result_summary")
                    ]
                    if budget_exceeded:
                        summaries.append(f"Token budget exhausted ({workflow_usage.total_tokens}/{token_budget})")
                    wf.result_summary = "\n".join(summaries) if summaries else "Workflow completed."
                    db.flush()

            _emit("workflow_complete", len(subtasks) - 1, "Workflow completed successfully")

        except Exception as exc:
            logger.error("Workflow %s execution error: %s", workflow_id, exc, exc_info=True)
            with get_session() as db:
                wf = db.get(Workflow, workflow_id)
                if wf:
                    wf.status = "failed"
                    wf.result_summary = f"Execution error: {exc}"
                    wf.completed_at = datetime.now(timezone.utc)
                    db.flush()

    def resume_workflow(
        self,
        workflow_id: str,
        config: dict,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Optional[Workflow]:
        """Resume a paused workflow from the next subtask after checkpoint."""
        with get_session() as db:
            wf = db.get(Workflow, workflow_id)
            if not wf or wf.status != "paused":
                return wf

            # Advance past the completed checkpoint step
            subtasks = list(wf.subtasks or [])
            current = wf.current_step
            # Mark the next pending step as ready
            if current + 1 < len(subtasks):
                wf.current_step = current + 1
            wf.status = "running"
            db.flush()
            db.expunge(wf)

        # Re-launch execution (will skip completed subtasks)
        self.execute_workflow(workflow_id, config, progress_callback)

        # Return fresh state
        return self.get_workflow(workflow_id)

    def retry_failed_step(
        self,
        workflow_id: str,
        step_index: int,
        config: dict,
        extra_turns: int = 30,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Optional[Workflow]:
        """Retry a failed workflow step with more turns (human-approved budget increase).

        Resets the failed step to 'pending', increases its turn budget,
        and resumes execution from that step.
        """
        with get_session() as db:
            wf = db.get(Workflow, workflow_id)
            if not wf:
                return None
            if wf.status not in ("failed", "paused", "completed"):
                return wf

            subtasks = list(wf.subtasks or [])
            if step_index < 0 or step_index >= len(subtasks):
                return wf

            step = subtasks[step_index]
            if step.get("status") != "failed":
                return wf

            # Reset the failed step and all subsequent steps
            step["status"] = "pending"
            step["error"] = None
            step["result_summary"] = ""
            step["started_at"] = None
            step["completed_at"] = None
            step["attempts"] = 1
            step["tokens_used"] = 0

            # Store the extra turns grant in the step for the executor to pick up
            step["extra_turns"] = extra_turns

            # Reset subsequent pending steps too
            for s in subtasks[step_index + 1:]:
                if s.get("status") in ("failed", "skipped"):
                    s["status"] = "pending"
                    s["error"] = None

            wf.subtasks = subtasks
            wf.current_step = step_index
            wf.status = "running"
            db.flush()
            db.expunge(wf)

        # Boost max_turns in the config for this execution
        boosted_config = dict(config)
        agent_cfg = dict(boosted_config.get("agent", {}))
        current_max = int(agent_cfg.get("max_turns", 30))
        agent_cfg["max_turns"] = current_max + extra_turns
        boosted_config["agent"] = agent_cfg

        # Re-launch execution (will skip completed subtasks, retry from step_index)
        self.execute_workflow(workflow_id, boosted_config, progress_callback)

        return self.get_workflow(workflow_id)

    # ------------------------------------------------------------------
    # Subtask Executors
    # ------------------------------------------------------------------

    def _resolve_repo_path(self, project_id: Optional[str], repo_id: Optional[str]) -> Optional[str]:
        """Resolve the repo path from project or repo record."""
        if project_id:
            with get_session() as db:
                project = db.get(TestProject, project_id)
                if project and project.local_path:
                    return project.local_path
                if project and project.repo_url:
                    return project.repo_url

        if repo_id:
            from src.data.models import Repo
            with get_session() as db:
                repo = db.get(Repo, repo_id)
                if repo and repo.local_path:
                    return repo.local_path
                if repo and repo.url:
                    return repo.url

        return None

    def _execute_discovery(
        self,
        project_id: Optional[str],
        subtask: dict,
        config: dict,
        repo_path: Optional[str],
    ) -> SubtaskResult:
        """Execute a discovery subtask."""
        try:
            from src.services.testing_service import TestingService
            service = TestingService()

            if project_id:
                project = service.run_discovery(project_id)
                if project and project.discovery_result:
                    discovery = project.discovery_result
                    ep_count = len(discovery.get("endpoints", []))
                    svc_count = len(discovery.get("services", []))
                    test_count = len(discovery.get("test_files", []))
                    frameworks = discovery.get("frameworks_detected", [])
                    summary = (
                        f"Discovered {ep_count} endpoints, {svc_count} services, "
                        f"{test_count} test files. Frameworks: {', '.join(frameworks) or 'none'}"
                    )
                    return SubtaskResult(success=True, summary=summary)
            elif repo_path and Path(repo_path).exists():
                discovery = service._discover_from_path(Path(repo_path))
                ep_count = len(discovery.get("endpoints", []))
                svc_count = len(discovery.get("services", []))
                summary = f"Discovered {ep_count} endpoints, {svc_count} services."
                return SubtaskResult(success=True, summary=summary)

            return SubtaskResult(success=True, summary="Discovery completed (no project path).")
        except Exception as exc:
            return SubtaskResult(success=False, summary=str(exc), error=str(exc))

    def _execute_agent(
        self,
        subtask: dict,
        config: dict,
        repo_path: Optional[str],
        working_memory: dict[str, str],
        goal: str,
        mode: str,
        wf_config: dict,
    ) -> SubtaskResult:
        """Execute an agent subtask — generate/modify code via AI agent."""
        if not repo_path or not Path(repo_path).exists():
            return SubtaskResult(
                success=False,
                summary="No valid repo path for agent execution.",
                error="repo_path not found",
            )

        try:
            from src.agent.analyzer import generate_changes_with_agent
            from src.agent.knowledge import load_repo_knowledge
            from src.code.executor import detect_build_tool
            from src.consciousness.core import build_or_load_consciousness

            ai_cfg = config.get("ai", {})
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
                return SubtaskResult(
                    success=False,
                    summary="No LLM API key configured.",
                    error="Missing API key",
                )

            agent_cfg = config.get("agent", {})
            base_max_turns = int(agent_cfg.get("max_turns", 30))
            agent_config = {
                "max_turns": base_max_turns,
                "smart_summarization": agent_cfg.get("smart_summarization", True),
                "truncation_limit": int(agent_cfg.get("truncation_limit", 30000)),
                "skip_tests": agent_cfg.get("skip_tests", False),
            }

            repo_url = wf_config.get("repo_url", "")
            consciousness = build_or_load_consciousness(repo_path, config, repo_url=repo_url)

            code_index = None
            try:
                from src.code_index import build_or_load_code_index
                code_index = build_or_load_code_index(
                    repo_path, config, repo_url=repo_url, consciousness=consciousness
                )
            except Exception:
                pass

            repo_knowledge = load_repo_knowledge(repo_path)
            build_tool = detect_build_tool(repo_path)

            # Build requirements from subtask description + context
            requirements = subtask.get("requirements") or subtask.get("description", "")
            if not requirements:
                requirements = f"Implement: {subtask.get('title', 'task')}"

            # Pass recipe_ids from workflow config if available
            recipe_ids = wf_config.get("recipe_ids") or None

            # Boost max_turns if attached recipe tools require more turns
            # (e.g. JISI downstream detector needs 75 turns for deep call chains)
            if recipe_ids:
                try:
                    from src.agent.recipe_context import get_recipe_max_turns
                    tool_max = get_recipe_max_turns(recipe_ids)
                    if tool_max > agent_config["max_turns"]:
                        agent_config["max_turns"] = tool_max
                        logger.info("Boosted max_turns to %d from recipe tool config", tool_max)
                except Exception:
                    pass

            result = generate_changes_with_agent(
                requirements,
                repo_path,
                llm_config=ai_cfg,
                verbose=ai_cfg.get("verbose", False),
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
                build_tool=build_tool,
                initial_working_memory=working_memory or None,
                recipe_ids=recipe_ids,
            )

            return SubtaskResult(
                success=result.success,
                summary=result.summary,
                files_changed=result.files_changed,
                working_memory=result.working_memory,
            )

        except Exception as exc:
            logger.error("Agent subtask failed: %s", exc, exc_info=True)
            return SubtaskResult(success=False, summary=str(exc), error=str(exc))

    def _execute_tests(
        self,
        subtask: dict,
        config: dict,
        repo_path: Optional[str],
    ) -> SubtaskResult:
        """Execute tests in the repo."""
        if not repo_path or not Path(repo_path).exists():
            return SubtaskResult(success=False, summary="No valid repo path.", error="repo_path not found")

        try:
            from src.code.executor import detect_project_type, run_tests

            project_type = detect_project_type(repo_path)
            exit_code, stdout, stderr = run_tests(repo_path, project_type, timeout=300)

            # Parse results
            combined = stdout + "\n" + stderr
            passed_m = re.search(r'(\d+)\s+passed', combined)
            failed_m = re.search(r'(\d+)\s+failed', combined)
            passed = int(passed_m.group(1)) if passed_m else 0
            failed = int(failed_m.group(1)) if failed_m else 0

            success = exit_code == 0 or (passed > 0 and failed == 0)
            summary = f"Tests: {passed} passed, {failed} failed (exit code {exit_code})"

            return SubtaskResult(success=success, summary=summary)

        except Exception as exc:
            return SubtaskResult(success=False, summary=str(exc), error=str(exc))

    def _execute_coverage(
        self,
        project_id: Optional[str],
        subtask: dict,
    ) -> SubtaskResult:
        """Run coverage analysis."""
        if not project_id:
            return SubtaskResult(success=True, summary="No project ID for coverage analysis.")

        try:
            from src.services.testing_service import TestingService
            service = TestingService()
            report = service.analyze_coverage(project_id)
            if report:
                summary = (
                    f"Coverage: {report.overall_pct}% overall, "
                    f"{len(report.uncovered_areas or [])} uncovered areas, "
                    f"{len(report.gaps or [])} gaps identified."
                )
                return SubtaskResult(success=True, summary=summary)
            return SubtaskResult(success=True, summary="Coverage analysis completed.")
        except Exception as exc:
            return SubtaskResult(success=False, summary=str(exc), error=str(exc))

    def _execute_command(
        self,
        subtask: dict,
        repo_path: Optional[str],
    ) -> SubtaskResult:
        """Run a shell command sandboxed to the repo directory."""
        command = subtask.get("description", "").strip()
        if not command:
            return SubtaskResult(success=False, summary="No command specified.", error="empty command")

        cwd = repo_path if repo_path and Path(repo_path).exists() else None

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=cwd,
            )
            success = result.returncode == 0
            output = (result.stdout or "")[-2000:]
            if result.stderr and not success:
                output += "\n" + (result.stderr or "")[-1000:]
            summary = f"Command exited with code {result.returncode}"
            if output.strip():
                summary += f": {output.strip()[:200]}"
            return SubtaskResult(success=success, summary=summary)
        except subprocess.TimeoutExpired:
            return SubtaskResult(success=False, summary="Command timed out (300s).", error="timeout")
        except Exception as exc:
            return SubtaskResult(success=False, summary=str(exc), error=str(exc))

    # ------------------------------------------------------------------
    # Pipeline Execution (Agent-to-Agent Orchestration)
    # ------------------------------------------------------------------

    def execute_pipeline(
        self,
        pipeline_id: str,
        repo_path: str,
        config: dict,
        repo_url: str = "",
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Execute an agent pipeline — ordered sequence of tools with shared context.

        Each step invokes a CustomTool as a sub-agent. Steps in the same
        parallel_group run concurrently. Findings are passed via PipelineContext.
        """
        import concurrent.futures
        from src.agent.knowledge import PipelineContext
        from src.data.models import AgentPipeline, CustomTool

        with get_session() as db:
            pipeline = db.get(AgentPipeline, pipeline_id)
            if not pipeline:
                return {"success": False, "error": f"Pipeline {pipeline_id} not found"}
            steps = list(pipeline.steps or [])
            pipeline_name = pipeline.name

        if not steps:
            return {"success": True, "summary": "Pipeline has no steps"}

        context = PipelineContext(pipeline_id=pipeline_id)
        results: list[dict] = []

        def _emit(msg: str):
            if progress_callback:
                progress_callback({"type": "pipeline", "message": msg, "pipeline_id": pipeline_id})

        _emit(f"Starting pipeline: {pipeline_name} ({len(steps)} steps)")

        # Group steps by parallel_group
        groups: dict[int, list[dict]] = {}
        for step in steps:
            group = step.get("parallel_group", step.get("index", 0))
            groups.setdefault(group, []).append(step)

        for group_num in sorted(groups.keys()):
            group_steps = groups[group_num]

            if len(group_steps) == 1:
                # Sequential execution
                step = group_steps[0]
                result = self._execute_pipeline_step(step, context, config, repo_path, repo_url, _emit)
                results.append(result)
                if not result.get("success", False):
                    _emit(f"Pipeline failed at step: {step.get('tool_id', 'unknown')}")
                    return {"success": False, "results": results, "error": result.get("error", "")}
            else:
                # Parallel execution
                _emit(f"Running {len(group_steps)} steps in parallel (group {group_num})")
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(group_steps)) as executor:
                    futures = {
                        executor.submit(
                            self._execute_pipeline_step, step, context, config, repo_path, repo_url, _emit
                        ): step
                        for step in group_steps
                    }
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        results.append(result)

        _emit(f"Pipeline completed: {len(results)} steps executed")
        return {
            "success": all(r.get("success", False) for r in results),
            "results": results,
            "summary": f"Pipeline '{pipeline_name}' completed ({len(results)} steps)",
        }

    def _execute_pipeline_step(
        self,
        step: dict,
        context: "PipelineContext",
        config: dict,
        repo_path: str,
        repo_url: str,
        emit_fn,
    ) -> dict:
        """Execute a single pipeline step using a CustomTool as sub-agent."""
        tool_id = step.get("tool_id", "")
        step_id = step.get("id", tool_id)

        emit_fn(f"Step: {step_id} (tool: {tool_id})")

        try:
            from src.data.models import CustomTool
            with get_session() as db:
                tool = db.get(CustomTool, tool_id)
                if not tool:
                    return {"success": False, "step_id": step_id, "error": f"Tool {tool_id} not found"}
                tool_name = tool.name
                agent_instructions = tool.agent_instructions
                max_turns = tool.max_turns

            # Resolve inputs from context
            step_inputs = context.get_context_for_step(step)
            input_context = "\n".join(f"- {k}: {v[:500]}" for k, v in step_inputs.items()) if step_inputs else ""

            # Build requirements
            requirements = agent_instructions
            if input_context:
                requirements += f"\n\n## Context from previous steps:\n{input_context}"

            # Run as sub-agent
            from src.agent.analyzer import generate_changes_with_agent
            from src.consciousness.core import build_or_load_consciousness

            ai_cfg = config.get("ai", {})
            consciousness = build_or_load_consciousness(repo_path, config, repo_url=repo_url)

            agent_config = {
                "max_turns": max_turns,
                "smart_summarization": True,
                "truncation_limit": 30000,
                "skip_tests": True,
            }

            result = generate_changes_with_agent(
                requirements, repo_path,
                llm_config=ai_cfg,
                verbose=False,
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                initial_working_memory=context.to_dict(),
            )

            # Write outputs to context
            output_keys = step.get("output_keys", [])
            for key in output_keys:
                context.write_step_output(step_id, key, result.summary or "")

            # Also store working memory from result
            if result.working_memory:
                for k, v in result.working_memory.items():
                    context.write_step_output(step_id, k, v)

            emit_fn(f"Step {step_id} completed: {result.summary[:100]}")

            return {
                "success": result.success,
                "step_id": step_id,
                "tool_name": tool_name,
                "summary": result.summary,
                "files_changed": result.files_changed,
            }

        except Exception as exc:
            emit_fn(f"Step {step_id} failed: {exc}")
            return {"success": False, "step_id": step_id, "error": str(exc)}
