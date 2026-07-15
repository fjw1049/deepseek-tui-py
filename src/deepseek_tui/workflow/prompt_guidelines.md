## Workflow tool

Use the `workflow` tool when the user explicitly asks for "workflow", multi-agent orchestration, phased review, or parallel fan-out. Do not replace that request with separate `agent_spawn` / `agent_wait` calls. Do not use `workflow` for a single straightforward task.

- Prefer a named workflow with `name` + `task` when one fits. Bundled presets: `repo_review`, `diff_review`, `spec_check`. Discovery roots (higher wins): `<cwd>/workflows/`, `<cwd>/.deepseek/workflows/`, `~/.deepseek/workflows/`, then built-in presets. Call `workflow_list` to enumerate available workflows and recent runs (and find a `run_id` to resume).
- Resume interrupted/failed runs with `run_id` (from `.deepseek/workflow-runs/`). Do not pass `run_id` together with `name`/`spec`.
- Do not pass both `name` and `spec`. For ad-hoc IR, pass a complete `spec` object (Workflow IR v1).
- Every agent step needs a unique `label` or `label_template`.
- Use `fanout` for parallel items; do not spawn many separate `agent_spawn` calls for the same work.
- Fanout may use static `items` **or** dynamic `items_from: { "step": "<prior_id>", "path": "$.field" }` (exactly one). Upstream steps should return structured JSON (prefer `output_schema`).
- Use `loop` with `max_rounds` and optional `until: { path, equals, step? }` for bounded refine/verify cycles. Templates support `{{round}}`.
- Per-step timeout: set `timeout_seconds` (1..3600) on `agent` / `fanout` / `synthesis` steps to cap one agent call. On timeout the agent is cancelled and the step produces no output (subject to `on_error`). Omit to keep the default long wait.
- `policy.token_budget` is declared but **not yet enforced** - setting it does not cap cost. Bound cost via `max_agents`, `concurrency`, `wall_clock_seconds`, and per-step `timeout_seconds`.
- Templates support `{{task}}`, `{{item}}`, `{{previous}}`, `{{round}}`, and `{{outputs.<step_id>}}`.
- When merging branches, include a `synthesis` step that references prior outputs via `{{outputs.<step_id>}}`.
- Failed steps may be omitted from outputs; synthesis prompts must tolerate missing references.
- Sub-agents do not inherit implicit repository context — include paths, files, and goals in prompts.
- Do not duplicate work with batch `agent_spawn` outside the workflow after starting a workflow.
- Opt-in isolation: set `policy.worktree` to `"on"` so the run edits a git worktree under `.deepseek/workflow-runs/<run_id>/tree` (fails closed if not a git repo). Default is `"off"`.
- Background long runs: pass `detach: true` to enqueue via TaskManager and return `run_id` + `task_id` immediately. Cancel with `task_cancel` / resume with `run_id` — Esc only stops waiting, not a detached run.

### Incremental examples (why these features exist)

Assume the user asks to review integration risk across `engine` / `tools` / `workbench`.

**Baseline (ad-hoc IR):** the model must invent a full graph and hard-code fanout `items`. Easy to omit fields, guess wrong targets, or lose a long run.

**Named run:** `{ "name": "repo_review", "task": "审查 engine/tools/workbench 集成风险" }` — pick a stable JSON preset; inject `{{task}}` at runtime.

**Dynamic fanout:** a plan step returns `{"targets":["engine","tools"]}`; fanout uses `items_from: { "step": "plan", "path": "$.targets" }` so spawn count follows the repo, not a guessed list (cap 16).

**Templates:** preset prompts use `{{task}}` / loop uses `{{round}}` so one JSON works for many tasks.

**Presets:** `repo_review` (plan → items_from fanout → synthesis), `diff_review` (lenses → fanout → synthesis), `spec_check` (extract reqs → map → report).

**Loop + until:** bounded refine until structured `done=true` or `max_rounds` — no dynamic JS controller required.

**Checkpoint resume:** interrupted runs leave `.deepseek/workflow-runs/<run_id>/run.json`; call `{ "run_id": "wf_..." }` to skip completed steps. Fanout also checkpoints each finished item (`{step}:{item}`) so mid-fanout resume skips done branches. **Loop caveat:** round index is not persisted — resume restarts an in-progress loop from round 1 (prefer idempotent loop bodies).

**Worktree:** with `policy.worktree: "on"`, mutating fanout agents share an isolated branch/worktree; the main checkout stays clean; resume reuses the same tree.

**Detach:** `{ "name": "...", "task": "...", "detach": true }` returns immediately; TaskManager drives the same `run_id` to a terminal state while the process/worker is alive.
