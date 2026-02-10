"""
Tests for agent plan mode: ChangePlan, generate_diff, apply_plan, execute_plan_tool.
"""

import os
import pytest
from pathlib import Path

from src.agent.plan import (
    ChangeAction,
    ProposedChange,
    ChangePlan,
    generate_diff,
    apply_plan,
)
from src.agent.tools import execute_plan_tool, build_plan_tools


# ---------------------------------------------------------------------------
# ChangePlan tests
# ---------------------------------------------------------------------------

class TestChangePlan:
    def test_empty_plan(self):
        plan = ChangePlan()
        assert plan.is_empty
        assert plan.files_affected == []

    def test_add_change(self):
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="src/foo.py", action=ChangeAction.create,
            description="Add foo", new_content="print('hello')",
        ))
        assert not plan.is_empty
        assert plan.files_affected == ["src/foo.py"]

    def test_merge_edits_same_file(self):
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="src/bar.py", action=ChangeAction.modify,
            description="Fix import",
            edits=[{"old_string": "import os", "new_string": "import sys"}],
        ))
        plan.add_change(ProposedChange(
            path="src/bar.py", action=ChangeAction.modify,
            description="Fix function",
            edits=[{"old_string": "def old():", "new_string": "def new():"}],
        ))
        # Should merge into one change with 2 edits
        assert len(plan.changes) == 1
        assert len(plan.changes[0].edits) == 2
        assert "Fix import" in plan.changes[0].description
        assert "Fix function" in plan.changes[0].description

    def test_no_merge_different_actions(self):
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="src/baz.py", action=ChangeAction.create,
            description="Create", new_content="content",
        ))
        plan.add_change(ProposedChange(
            path="src/baz.py", action=ChangeAction.modify,
            description="Modify",
            edits=[{"old_string": "a", "new_string": "b"}],
        ))
        assert len(plan.changes) == 2

    def test_files_affected_preserves_order(self):
        plan = ChangePlan()
        plan.add_change(ProposedChange(path="c.py", action=ChangeAction.create, new_content=""))
        plan.add_change(ProposedChange(path="a.py", action=ChangeAction.create, new_content=""))
        plan.add_change(ProposedChange(path="b.py", action=ChangeAction.create, new_content=""))
        assert plan.files_affected == ["c.py", "a.py", "b.py"]

    def test_to_dict(self):
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="x.py", action=ChangeAction.create,
            description="test", new_content="hello",
        ))
        d = plan.to_dict()
        assert len(d) == 1
        assert d[0]["path"] == "x.py"
        assert d[0]["action"] == "create"
        assert d[0]["new_content"] == "hello"


# ---------------------------------------------------------------------------
# generate_diff tests
# ---------------------------------------------------------------------------

class TestGenerateDiff:
    def test_create_new_file(self, tmp_path):
        change = ProposedChange(
            path="new_file.py", action=ChangeAction.create,
            new_content="line1\nline2\n",
        )
        diff = generate_diff(tmp_path, change)
        assert "--- /dev/null" in diff
        assert "+++ new_file.py" in diff
        assert "+line1" in diff
        assert "+line2" in diff

    def test_delete_file(self, tmp_path):
        (tmp_path / "old_file.py").write_text("goodbye\n")
        change = ProposedChange(
            path="old_file.py", action=ChangeAction.delete,
        )
        diff = generate_diff(tmp_path, change)
        assert "--- old_file.py" in diff
        assert "+++ /dev/null" in diff
        assert "-goodbye" in diff

    def test_modify_surgical_edit(self, tmp_path):
        (tmp_path / "edit_me.py").write_text("import os\nprint('hello')\n")
        change = ProposedChange(
            path="edit_me.py", action=ChangeAction.modify,
            edits=[{"old_string": "import os", "new_string": "import sys"}],
        )
        diff = generate_diff(tmp_path, change)
        assert "-import os" in diff
        assert "+import sys" in diff
        assert "print('hello')" in diff or "+print" not in diff

    def test_modify_full_replacement(self, tmp_path):
        (tmp_path / "replace_me.py").write_text("old content\n")
        change = ProposedChange(
            path="replace_me.py", action=ChangeAction.modify,
            new_content="new content\n",
        )
        diff = generate_diff(tmp_path, change)
        assert "-old content" in diff
        assert "+new content" in diff

    def test_create_empty_file(self, tmp_path):
        change = ProposedChange(
            path="empty.py", action=ChangeAction.create,
            new_content="",
        )
        diff = generate_diff(tmp_path, change)
        # No content lines, but should still have headers
        assert "--- /dev/null" in diff or diff == ""


# ---------------------------------------------------------------------------
# apply_plan tests
# ---------------------------------------------------------------------------

class TestApplyPlan:
    def test_apply_create(self, tmp_path):
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="new.py", action=ChangeAction.create,
            new_content="print('created')\n",
        ))
        files = apply_plan(tmp_path, plan)
        assert "new.py" in files
        assert (tmp_path / "new.py").read_text() == "print('created')\n"

    def test_apply_modify_surgical(self, tmp_path):
        (tmp_path / "mod.py").write_text("import os\nprint('hi')\n")
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="mod.py", action=ChangeAction.modify,
            edits=[{"old_string": "import os", "new_string": "import sys"}],
        ))
        files = apply_plan(tmp_path, plan)
        assert "mod.py" in files
        content = (tmp_path / "mod.py").read_text()
        assert "import sys" in content
        assert "import os" not in content

    def test_apply_modify_full_replacement(self, tmp_path):
        (tmp_path / "rep.py").write_text("old\n")
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="rep.py", action=ChangeAction.modify,
            new_content="new\n",
        ))
        files = apply_plan(tmp_path, plan)
        assert "rep.py" in files
        assert (tmp_path / "rep.py").read_text() == "new\n"

    def test_apply_delete(self, tmp_path):
        (tmp_path / "del.py").write_text("bye\n")
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="del.py", action=ChangeAction.delete,
        ))
        files = apply_plan(tmp_path, plan)
        assert "del.py" in files
        assert not (tmp_path / "del.py").exists()

    def test_apply_mixed(self, tmp_path):
        (tmp_path / "existing.py").write_text("old_line\n")
        plan = ChangePlan()
        plan.add_change(ProposedChange(
            path="brand_new.py", action=ChangeAction.create,
            new_content="new file\n",
        ))
        plan.add_change(ProposedChange(
            path="existing.py", action=ChangeAction.modify,
            edits=[{"old_string": "old_line", "new_string": "new_line"}],
        ))
        files = apply_plan(tmp_path, plan)
        assert len(files) == 2
        assert (tmp_path / "brand_new.py").exists()
        assert "new_line" in (tmp_path / "existing.py").read_text()


# ---------------------------------------------------------------------------
# execute_plan_tool tests
# ---------------------------------------------------------------------------

class TestExecutePlanTool:
    def test_propose_create(self, tmp_path):
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "new.py", "action": "create", "description": "New file", "content": "hello"},
            change_plan=plan,
        )
        assert "Proposed: CREATE" in result
        assert len(plan.changes) == 1

    def test_propose_modify_surgical(self, tmp_path):
        (tmp_path / "src.py").write_text("import os\nfoo\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "src.py", "action": "modify", "description": "Fix",
             "old_string": "import os", "new_string": "import sys"},
            change_plan=plan,
        )
        assert "Proposed: MODIFY" in result
        assert "surgical" in result

    def test_propose_modify_old_string_not_found(self, tmp_path):
        (tmp_path / "src.py").write_text("import os\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "src.py", "action": "modify", "description": "Fix",
             "old_string": "import sys", "new_string": "import io"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert "not found" in result
        assert plan.is_empty

    def test_propose_modify_old_string_not_unique(self, tmp_path):
        (tmp_path / "dup.py").write_text("x = 1\nx = 1\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "dup.py", "action": "modify", "description": "Fix",
             "old_string": "x = 1", "new_string": "x = 2"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert "2 times" in result

    def test_propose_delete(self, tmp_path):
        (tmp_path / "del.py").write_text("bye\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "del.py", "action": "delete", "description": "Remove"},
            change_plan=plan,
        )
        assert "Proposed: DELETE" in result
        assert len(plan.changes) == 1

    def test_propose_delete_nonexistent(self, tmp_path):
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "ghost.py", "action": "delete", "description": "Remove"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert plan.is_empty

    def test_blocked_write_tools(self, tmp_path):
        plan = ChangePlan()
        for tool in ["write_file", "edit_file", "delete_file", "run_command"]:
            result = execute_plan_tool(
                tmp_path, tool, {"path": "x", "content": "y"},
                change_plan=plan,
            )
            assert "not available in plan mode" in result

    def test_read_tools_delegated(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello world\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "read_file", {"path": "readme.txt"},
            change_plan=plan,
        )
        assert "hello world" in result

    def test_invalid_action(self, tmp_path):
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "x.py", "action": "rename", "description": "Bad"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert "rename" in result

    def test_propose_create_missing_content(self, tmp_path):
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "x.py", "action": "create", "description": "No content"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert "content is required" in result

    def test_propose_modify_no_edit_info(self, tmp_path):
        (tmp_path / "m.py").write_text("data\n")
        plan = ChangePlan()
        result = execute_plan_tool(
            tmp_path, "propose_change",
            {"path": "m.py", "action": "modify", "description": "Incomplete"},
            change_plan=plan,
        )
        assert result.startswith("Error:")
        assert "requires either" in result


# ---------------------------------------------------------------------------
# build_plan_tools tests
# ---------------------------------------------------------------------------

class TestBuildPlanTools:
    def test_plan_tools_include_propose_change(self):
        tools = build_plan_tools()
        names = [t["function"]["name"] for t in tools]
        assert "propose_change" in names
        assert "read_file" in names
        assert "task_complete" in names
        assert "update_memory" in names

    def test_plan_tools_exclude_write(self):
        tools = build_plan_tools()
        names = [t["function"]["name"] for t in tools]
        assert "write_file" not in names
        assert "edit_file" not in names
        assert "delete_file" not in names
        assert "run_command" not in names
