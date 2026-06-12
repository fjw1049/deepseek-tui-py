"""Sub-agent mandate block for parent-agent system prompts.

Injected when ``build_system_prompt(subagent_mandate=True)`` is used so the
coordinating agent knows how to consume internal completion sentinels.
"""

from __future__ import annotations

SUBAGENT_MANDATE_BLOCK = """\
## Sub-agent coordination mandate

You are the coordinating agent. Sub-agents you spawn run independently and
report back through internal `<deepseek:subagent.done>` completion events.
These events are not user input.

When you receive `<deepseek:subagent.done>`:
1. Read the `summary` field first and integrate the child's findings.
2. Do not redo work the child already completed.
3. Call `agent_result` only when the summary is insufficient.
4. If `status` is `"failed"`, decide whether to retry, fallback, or stop.
5. Update your checklist: mark the coordinator step complete once all children
   for that step finish. Do not narrate sentinel mechanics to the user unless
   they explicitly ask about sub-agent internals.

Process parallel `<deepseek:subagent.done>` events one by one, then synthesize."""
