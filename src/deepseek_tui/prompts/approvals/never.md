## Approval Policy: Never

All write operations are blocked. You can read, search, trace logic, and inspect existing sub-agents, but you cannot modify the workspace, run shell commands, or spawn new sub-agents.

Do not request write approvals. When the plan is ready, call `exit_plan_mode` so the user can accept, revise, or leave plan mode.
