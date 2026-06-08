# Goal — Token-Budgeted Thread Goal Tracking

The `goal` module provides autonomous, token-budgeted goal tracking for DeepSeek TUI threads. It lets users assign an objective to a conversation thread, tracks token usage and wall-clock time against an optional budget, persists state to a crash-safe append-only journal, and automatically steers the model through continuation prompts, budget-limit warnings, and failure recovery.

## Overview

```
┌──────────────────────────────────────────────────┐
│                  GoalController                  │
│  (orchestrator — turn hooks + lifecycle ops)     │
├──────────────────────────────────────────────────┤
│  transition  │  state  │  accounting  │  prompts │
│  (validate)  │ (pure)  │  (time/token)│  (text)  │
├──────────────┴─────────┴──────────────┴──────────┤
│  persistence (GoalJournal — JSONL on disk)        │
│  recovery    (failure classification)             │
│  tools       (model-callable: get/create/update)  │
└──────────────────────────────────────────────────┘
```

## File Map

| File | Responsibility |
|------|----------------|
| `models.py` | Data structures: `ThreadGoal`, `GoalEntry`, `GoalUsage`, `GoalStatus` |
| `state.py` | Pure functions: create, apply usage, update status, reconstruct from journal |
| `persistence.py` | `GoalJournal` — append-only JSONL journal; thread ID resolution; fork copying |
| `transition.py` | Validates and plans state transitions (create / pause / resume / complete / clear) |
| `accounting.py` | Turn-level token and wall-clock-time tracking |
| `prompts.py` | Generates continuation markers and budget-limit steer messages for the model |
| `continuation.py` | `GoalFollowUp` — queues a prompt to keep the agent working on an active goal |
| `controller.py` | Orchestrator: wires lifecycle hooks, tools, and persistence together |
| `recovery.py` | Classifies failures and decides whether to retry, pause, or wait |
| `stale_guard.py` | Checks that a pending follow-up prompt still matches the current goal |
| `tools.py` | Model-callable tools: `get_goal`, `create_goal`, `update_goal` |

## Lifecycle

```
         create()
            │
            ▼
    ┌─── ACTIVE ──────────────────────┐
    │     │          │                 │
    │   pause()   budget exhausted   complete()
    │     │          │                 │
    │     ▼          ▼                 ▼
    │  PAUSED    BUDGET_LIMITED    COMPLETE
    │     │
    │  resume()
    │     │
    └─────┘
            │
         clear()
            │
            ▼
        (deleted)
```

### States

- **ACTIVE** — goal is set and the agent works on it each turn.
- **PAUSED** — goal exists but the agent won't resume it automatically (user cancelled, failure threshold hit).
- **BUDGET_LIMITED** — token budget reached; the model is asked to pause and summarize.
- **COMPLETE** — goal marked done (model or user). Terminal.

### Transitions

| From | Request | To | Guard |
|------|---------|----|-------|
| (none) | `create` | ACTIVE | Must not have an existing active goal; use `replace_existing=true` to override |
| ACTIVE | `pause` | PAUSED | — |
| ACTIVE | `complete` | COMPLETE | — |
| PAUSED | `resume` | ACTIVE | Cannot resume COMPLETE or BUDGET_LIMITED goals |
| ACTIVE | budget hit | BUDGET_LIMITED | Automatic when `tokens_used >= token_budget` |
| any | `clear` | deleted | Removes goal and journal entry |

## Journal (Persistence)

Goal state is persisted as an **append-only JSONL journal** under `.deepseek/goals/{thread_id}.jsonl`. Each entry has a `type`:

- **`set`** — a goal snapshot (create, pause, resume, complete, budget-limited transitions).
- **`usage`** — token and time delta for one turn.
- **`clear`** — goal was removed.

Goals are reconstructed by replaying all entries. The journal is crash-safe (line-by-line append + `fsync`) and fork-aware (copying a journal auto-pauses the active goal on the forked branch).

## Failure Recovery

Failures are classified into four categories and handled per-turn:

| Failure Kind | Trigger | Action |
|--------------|---------|--------|
| `USER_CANCEL` | `user_cancelled`, `interrupt_requested` | Pause goal immediately |
| `FATAL` | quota, auth, rate-limit, permission | Pause goal immediately |
| `CONTEXT_OVERFLOW` | `context_overflow` | Retry up to `max_overflow_failures` (default 3), then pause |
| `TRANSIENT` | anything else | Retry up to `max_consecutive_failures` (default 3), then pause |

## Turn Lifecycle Integration

The controller is called at three points during each turn:

1. **`on_turn_start()`** — starts the wall-clock timer.
2. **`on_turn_complete(usage)`** — records token/time usage; auto-transitions to `BUDGET_LIMITED` if over budget; returns a `GoalFollowUp` continuation prompt for the next turn if the goal is still active.
3. **`on_turn_failed(reason)`** — classifies the failure, records usage, and potentially pauses the goal.

## Model Tools

Three tools expose goal operations to the agent:

- **`get_goal`** — returns current goal, status, budget, and usage. Read-only.
- **`create_goal`** — sets a new goal with optional token budget. Fails if an active goal exists unless `replace_existing=true`.
- **`update_goal`** — marks the goal `complete`. The model may only transition to `complete` through this tool (it cannot pause, resume, or clear via tools — those are user-initiated).

## Key Constraints

- Maximum objective length: 12,000 characters.
- Minimum token budget: 1,000 tokens.
- Thread IDs are sanitized (alphanumeric, `-`, `_` only) for safe filesystem paths.
- The continuation prompt is wrapped in an XML marker (`<deepseek_goal_continuation>`) with the goal ID, so the model can verify it's working on the right goal.

## Usage Example (via Controller)

```python
from deepseek_tui.goal import GoalController

ctrl = GoalController(workspace=Path("/project"), thread_id="abc123")

# Set a goal with budget
goal = ctrl.create("Refactor the auth module", token_budget=50_000)

# Turn lifecycle
ctrl.on_turn_start()
# ... agent does work ...
follow_up = ctrl.on_turn_complete(usage)  # records tokens + time
# follow_up.content contains the continuation prompt for the next turn

# Mark done
ctrl.complete("auth module refactored")
```
