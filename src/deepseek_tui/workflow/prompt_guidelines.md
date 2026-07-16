## Workflow tool

Use the `workflow` tool when the user explicitly asks for "workflow", multi-agent orchestration, phased review, parallel fan-out, or adaptive dynamic planning. Do not replace that request with separate `agent_spawn` / `agent_wait` calls. Do not use `workflow` for a single straightforward task.

- Prefer a named workflow with `name` + `task` when one fits. Bundled presets: `repo_review`, `diff_review`, `spec_check`, `adaptive`. Discovery roots (higher wins): `<cwd>/workflows/`, `<cwd>/.deepseek/workflows/`, `~/.deepseek/workflows/`, then built-in presets. Call `workflow_list` to enumerate available workflows and recent runs (and find a `run_id` to resume).
- For open-ended orchestration without a fixed graph, use `{ "mode": "dynamic", "task": "..." }` or `name: "adaptive"` — a dynamic controller mutates the runtime DAG (spawn/fanout/reduce/synthesize/stop) under budgets.
- Resume interrupted/failed runs with `run_id` (from `.deepseek/workflow-runs/`). Do not pass `run_id` together with `name`/`spec`/`mode`.
- Do not pass both `name` and `spec`. For ad-hoc IR, pass a complete `spec` object (Workflow IR v1 phases or v2 `graph`).
- Every agent step needs a unique `label` or `label_template`.
- Use `fanout` for parallel items; do not spawn many separate `agent_spawn` calls for the same work.
- Fanout may use static `items` **or** dynamic `items_from: { "step": "<prior_id>", "path": "$.field" }` (exactly one). Upstream steps should return structured JSON (prefer `output_schema`).
- Use `reduce` (or `synthesis`) for multi-predecessor joins. Prefer explicit v2 edges for A,B→C DAGs.
- Use `loop` with `max_rounds` and optional `until: { path, equals, step? }` for bounded refine/verify cycles. Templates support `{{round}}`.
- `support` nodes call allowlisted helpers (`dedupe_findings`, `flatten_previews`, `merge_json`).
- Per-step timeout: set `timeout_seconds` (1..3600) on agent-like steps to cap one agent call. On timeout the agent is cancelled and the step produces no output (subject to `on_error`). Omit to keep the default long wait.
- `policy.token_budget` is enforced via a rough char/4 estimate of prompts/outputs (not a provider tokenizer). Bound wall time via `max_agents`, `concurrency`, `wall_clock_seconds`, and per-step `timeout_seconds`.
- Templates support `{{task}}`, `{{item}}`, `{{previous}}`, `{{round}}`, and `{{outputs.<step_id>}}`.
- When merging branches, include a `reduce`/`synthesis` step that references prior outputs via `{{outputs.<step_id>}}`.
- Failed steps may be omitted from outputs; synthesis/reduce prompts must tolerate missing references (`source_policy: partial` default for reduce).
- Sub-agents do not inherit implicit repository context — include paths, files, and goals in prompts.
- Do not duplicate work with batch `agent_spawn` outside the workflow after starting a workflow.
- Opt-in isolation: set `policy.worktree` to `"on"` so the run edits a git worktree under `.deepseek/workflow-runs/<run_id>/tree` (fails closed if not a git repo). Default is `"off"`.
- Background long runs: pass `detach: true` to enqueue via TaskManager and return `run_id` + `task_id` immediately. Cancel with `task_cancel` / resume with `run_id` — Esc only stops waiting, not a detached run.

### Incremental examples (why these features exist)

Assume the user asks to review integration risk across `engine` / `tools` / `workbench`.

**Baseline (ad-hoc IR):** the model must invent a full graph and hard-code fanout `items`. Easy to omit fields, guess wrong targets, or lose a long run.

**Named run:** `{ "name": "repo_review", "task": "审查 engine/tools/workbench 集成风险" }` — pick a stable JSON preset; inject `{{task}}` at runtime.

**Adaptive / dynamic:** `{ "mode": "dynamic", "task": "…" }` — controller decides spawn/fanout/reduce at runtime under budgets; checkpoint stores graph mutations for resume.

**Dynamic fanout:** a plan step returns `{"targets":["engine","tools"]}`; fanout uses `items_from: { "step": "plan", "path": "$.targets" }` so spawn count follows the repo, not a guessed list (cap 16).

**Templates:** preset prompts use `{{task}}` / loop uses `{{round}}` so one JSON works for many tasks.

**Presets:** `repo_review` (plan → fanout → reduce DAG), `diff_review` (lenses → fanout → synthesis), `spec_check` (extract reqs → map → report), `adaptive` (dynamic root).

**Loop + until:** bounded refine until structured `done=true` or `max_rounds`.

**Checkpoint resume:** interrupted runs leave `.deepseek/workflow-runs/<run_id>/run.json`; call `{ "run_id": "wf_..." }` to skip completed steps and restore runtime graph / dynamic state. Fanout also checkpoints each finished item (`{step}:{item}`) so mid-fanout resume skips done branches.

**Worktree:** with `policy.worktree: "on"`, mutating fanout agents share an isolated branch/worktree; the main checkout stays clean; resume reuses the same tree.

**Detach:** `{ "name": "...", "task": "...", "detach": true }` returns immediately; TaskManager drives the same `run_id` to a terminal state while the process/worker is alive.
