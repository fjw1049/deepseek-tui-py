## Workflow tool

Use the `workflow` tool when the user explicitly asks for "workflow", multi-agent orchestration, phased review, or parallel fan-out. Do not replace that request with separate `agent_spawn` / `agent_wait` calls. Do not use `workflow` for a single straightforward task.

- Pass a complete `spec` object (Workflow IR v1). Do not pass Python, JavaScript, or markdown-fenced code strings.
- Every agent step needs a unique `label` or `label_template`.
- Use `fanout` for parallel items; do not spawn many separate `agent_spawn` calls for the same work.
- When merging branches, include a `synthesis` step that references prior outputs via `{{outputs.<step_id>}}`.
- Failed steps may be omitted from outputs; synthesis prompts must tolerate missing references.
- Sub-agents do not inherit implicit repository context — include paths, files, and goals in prompts.
- Do not duplicate work with batch `agent_spawn` outside the workflow after starting a workflow.
