"""
AgentService — wraps agent/plan/ask execution with session tracking.

Each invocation creates a Session record, starts a Trace, and returns
a structured result. Progress is reported via an optional callback.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.agent.knowledge import compute_repo_id

logger = logging.getLogger(__name__)

# Type alias for progress callbacks
ProgressCallback = Optional[Callable[[dict], None]]


class AgentService:
    """Service for running agent, plan, and ask sessions."""

    def _append_session_log(self, session_id, entry):
        """Append an entry to the session's log column."""
        if not session_id:
            return
        try:
            from src.data.database import get_session
            from src.data.models import Session as SessionModel

            entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            with get_session() as db:
                s = db.get(SessionModel, session_id)
                if s:
                    s.log = (s.log or []) + [entry]
                    db.flush()
        except Exception:
            pass

    def _checkout_branch(self, repo_path: str, branch: str):
        """Checkout a specific branch before running the agent."""
        if branch:
            try:
                from src.platform.git_ops import checkout_branch
                checkout_branch(repo_path, branch, create=False)
                logger.info("Checked out branch: %s", branch)
            except Exception as exc:
                logger.warning("Could not checkout branch %s: %s", branch, exc)

    def _build_agent_config(self, config: dict) -> dict:
        """Extract agent config section from full config."""
        agent_cfg = config.get("agent", {})
        return {
            "max_turns": int(agent_cfg.get("max_turns", 50)),
            "smart_summarization": agent_cfg.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg.get("truncation_limit", 30000)),
            "command_allowlist_only": agent_cfg.get("command_allowlist_only", False),
            "allowed_command_prefixes": agent_cfg.get("allowed_command_prefixes", []),
            "blocked_commands": agent_cfg.get("blocked_commands", []),
            "summarization_budget": int(agent_cfg.get("summarization_budget", 0)),
            "testing_budget": int(agent_cfg.get("testing_budget", 0)),
            "skip_tests": agent_cfg.get("skip_tests", False),
        }

    def _create_session(self, repo_id: str, mode: str, requirements: str) -> Optional[str]:
        """Create a Session record in the database. Returns session_id or None."""
        try:
            from src.data.database import get_session, init_db
            from src.data.repositories import RepoRepository, SessionRepository

            init_db()
            session_id = uuid.uuid4().hex[:16]
            with get_session() as db:
                RepoRepository(db).get_or_create(repo_id)
                SessionRepository(db).create(
                    repo_id=repo_id,
                    mode=mode,
                    requirements=requirements[:2000],
                    session_id=session_id,
                )
            return session_id
        except Exception as exc:
            logger.debug("Could not create session record: %s", exc)
            return None

    def _update_session(
        self,
        session_id: Optional[str],
        status: str,
        result_summary: str = "",
        turns_used: int = 0,
        trace_id: str = "",
    ) -> None:
        """Update a Session record in the database."""
        if not session_id:
            return
        try:
            from src.data.database import get_session
            from src.data.repositories import SessionRepository

            with get_session() as db:
                SessionRepository(db).update_status(
                    session_id, status, result_summary, turns_used, trace_id
                )
        except Exception as exc:
            logger.debug("Could not update session record: %s", exc)

    def run_agent(
        self,
        repo_path: str,
        requirements: str,
        config: dict,
        repo_url: str = "",
        resume: bool = False,
        branch: str = "",
        progress_callback: ProgressCallback = None,
        conversation_context: Optional[list[dict]] = None,
    ) -> "AgentResult":
        """Run agent mode — full agentic loop with exploration, editing, and testing."""
        from src.agent.analyzer import generate_changes_with_agent
        from src.agent.knowledge import load_repo_knowledge
        from src.code.executor import detect_build_tool
        from src.consciousness.core import build_or_load_consciousness

        self._checkout_branch(repo_path, branch)
        repo_id = compute_repo_id(repo_path, repo_url)
        ai_cfg = config["ai"]
        agent_config = self._build_agent_config(config)

        # Create session record
        session_id = self._create_session(repo_id, "agent", requirements)

        # Build consciousness and code index
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

        from src.agent.activity import set_progress_callback, clear_progress_callback

        def _combined_callback(event):
            self._append_session_log(session_id, event.get("data", {}))
            if progress_callback:
                progress_callback(event)

        set_progress_callback(_combined_callback)
        try:
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
                resume=resume,
                build_tool=build_tool,
                conversation_context=conversation_context,
            )
        except Exception as exc:
            clear_progress_callback()
            if progress_callback:
                progress_callback({"type": "error", "data": {"message": str(exc)}})
            self._update_session(session_id, "failed", str(exc))
            raise
        finally:
            clear_progress_callback()

        # Update session
        status = "completed" if result.success else "failed"
        self._update_session(
            session_id, status,
            result_summary=result.summary,
            turns_used=result.turns_used,
            trace_id=result.trace_id,
        )

        if progress_callback:
            progress_callback({"type": "complete", "data": {"summary": result.summary, "success": result.success}})

        return result

    def run_plan(
        self,
        repo_path: str,
        requirements: str,
        config: dict,
        repo_url: str = "",
        branch: str = "",
        progress_callback: ProgressCallback = None,
        conversation_context: Optional[list[dict]] = None,
    ) -> "PlanResult":
        """Run plan mode — read-only exploration + proposed changes."""
        from src.agent.analyzer import generate_plan_with_agent
        from src.agent.knowledge import load_repo_knowledge
        from src.code.executor import detect_build_tool
        from src.consciousness.core import build_or_load_consciousness

        self._checkout_branch(repo_path, branch)
        repo_id = compute_repo_id(repo_path, repo_url)
        ai_cfg = config["ai"]
        agent_cfg = config.get("agent", {})
        agent_config = {
            "plan_max_turns": int(agent_cfg.get("plan_max_turns", 30)),
            "max_turns": int(agent_cfg.get("max_turns", 50)),
            "smart_summarization": agent_cfg.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg.get("truncation_limit", 30000)),
        }

        session_id = self._create_session(repo_id, "plan", requirements)

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

        from src.agent.activity import set_progress_callback, clear_progress_callback

        def _combined_callback(event):
            self._append_session_log(session_id, event.get("data", {}))
            if progress_callback:
                progress_callback(event)

        set_progress_callback(_combined_callback)
        try:
            result = generate_plan_with_agent(
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
                conversation_context=conversation_context,
            )
        except Exception as exc:
            clear_progress_callback()
            if progress_callback:
                progress_callback({"type": "error", "data": {"message": str(exc)}})
            self._update_session(session_id, "failed", str(exc))
            raise
        finally:
            clear_progress_callback()

        status = "completed" if result.success else "failed"
        self._update_session(
            session_id, status,
            result_summary=result.summary,
            turns_used=result.turns_used,
            trace_id=result.trace_id,
        )

        if progress_callback:
            progress_callback({"type": "complete", "data": {"summary": result.summary, "success": result.success}})

        return result

    def run_ask(
        self,
        repo_path: str,
        question: str,
        config: dict,
        repo_url: str = "",
        branch: str = "",
        progress_callback: ProgressCallback = None,
        conversation_context: Optional[list[dict]] = None,
    ) -> "AskResult":
        """Run ask mode — answer a question about the codebase."""
        from src.agent.analyzer import generate_answer_with_agent
        from src.agent.knowledge import load_repo_knowledge
        from src.consciousness.core import build_or_load_consciousness

        self._checkout_branch(repo_path, branch)
        repo_id = compute_repo_id(repo_path, repo_url)
        ai_cfg = config["ai"]
        agent_cfg = config.get("agent", {})
        agent_config = {
            "ask_max_turns": int(agent_cfg.get("ask_max_turns", 20)),
            "max_turns": int(agent_cfg.get("max_turns", 50)),
            "smart_summarization": agent_cfg.get("smart_summarization", True),
            "truncation_limit": int(agent_cfg.get("truncation_limit", 30000)),
        }

        session_id = self._create_session(repo_id, "ask", question)

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

        from src.agent.activity import set_progress_callback, clear_progress_callback

        def _combined_callback(event):
            self._append_session_log(session_id, event.get("data", {}))
            if progress_callback:
                progress_callback(event)

        set_progress_callback(_combined_callback)
        try:
            result = generate_answer_with_agent(
                question,
                repo_path,
                llm_config=ai_cfg,
                verbose=ai_cfg.get("verbose", False),
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
                conversation_context=conversation_context,
            )
        except Exception as exc:
            clear_progress_callback()
            if progress_callback:
                progress_callback({"type": "error", "data": {"message": str(exc)}})
            self._update_session(session_id, "failed", str(exc))
            raise
        finally:
            clear_progress_callback()

        status = "completed" if result.success else "failed"
        self._update_session(
            session_id, status,
            result_summary=result.answer if result.success else result.summary,
            turns_used=result.turns_used,
            trace_id=result.trace_id,
        )

        if progress_callback:
            progress_callback({"type": "complete", "data": {"summary": result.answer if result.success else result.summary, "success": result.success}})

        return result
