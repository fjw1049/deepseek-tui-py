from deepseek_tui.goal.tools import GetGoalTool, SetGoalBudgetTool, UpdateGoalTool
from deepseek_tui.tools.registry import ApprovalRequirement
from deepseek_tui.tools.subagent.tools import AgentTool
from deepseek_tui.tools.task.tools import TaskOutputTool


def test_goal_mutations_are_not_readonly_but_keep_existing_approval():
    assert GetGoalTool().is_read_only()
    for tool in (UpdateGoalTool(), SetGoalBudgetTool()):
        assert not tool.is_read_only()
        assert not tool.supports_parallel()
        assert tool.approval_requirement() == ApprovalRequirement.AUTO


def test_agent_union_and_resume_are_not_readonly():
    tool = AgentTool()
    assert not tool.is_read_only()
    assert tool.is_read_only_for_input({"action": "wait"})
    assert not tool.is_read_only_for_input({"action": "wait", "resume": "existing"})


def test_task_output_distinguishes_inspection_from_archival():
    tool = TaskOutputTool()
    assert not tool.is_read_only()
    assert tool.is_read_only_for_input({"task_id": "t"})
    assert tool.is_read_only_for_input({"process_id": "p"})
    assert not tool.is_read_only_for_input({"task_id": "t", "process_id": "p"})
