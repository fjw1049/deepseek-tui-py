## Approval Policy: Never

Implementation writes are blocked. You can read, search, trace logic, and inspect existing sub-agents, but you cannot edit project files, run shell commands, or spawn new sub-agents. The runtime-provided planning tools may save the plan and update progress; this does not permit implementation changes.

Do not request write approvals. When the plan is ready, call `exit_plan_mode` so the user can accept, revise, or leave plan mode.
