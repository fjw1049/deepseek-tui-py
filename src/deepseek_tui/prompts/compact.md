## Compaction Handoff

You are writing a handoff for the *same* coding session after older messages are archived.
The continuing assistant will see: this summary inside `<archived_context>`, the user's requests quoted verbatim in `<prior_user_requests>`, and a few recent verbatim messages.
It will **not** see the full archived tool outputs. Write enough to continue seamlessly.

Output **only** Markdown with these headings (in this order). Keep every heading even if a section is empty — write `None` or `（无）` then.
Do not call tools. Do not wrap the output in XML. Do not add a preamble or closing remarks.
Preserve exact file paths, commands, errors, and decisions. Abbreviate repetitive tool dumps.

Two rules about who said what:

- The transcript labels each line `User:`, `Assistant:` or `Harness:`. Only `User:` lines are the human. `Harness:` lines are automated injections from the runtime, and `Assistant:` lines may *quote or paraphrase* the user — neither is evidence the user said anything. Never turn them into a user request or a user constraint. If you are unsure who wanted something, describe it as a decision, not as a user instruction.
- The user's own requests are carried verbatim in a separate block and do not depend on you. Do not spend this summary re-paraphrasing them. Spend it on what cannot be recovered any other way: what was tried, what it produced, what was decided, and why.

### Goal
[The user's high-level objective for this session]

### Constraints
[What bounds the work. Two kinds, both needed:
- stated: what the user ruled out or asked not to touch
- discovered: what the work revealed — a version pin, a flaky test, an API that rejects a value, a command that must run from a specific directory
Quote discovered constraints in the exact words of the error or output that established them. A paraphrased constraint gets re-litigated; a quoted one does not.]

### Progress

#### Done
[What's complete and verified — landed commits, passing tests, shipped patches]

#### In Progress
[What's mid-flight — partial implementations, open PRs, work-in-tree]

#### Blocked
[What's stuck, why, and what would unblock it]

### Key Decisions
[Architectural choices, design decisions, trade-offs made — the WHY behind the work]

### Next step
[The single next action to take when resuming — one line, concrete.
Anchor it: name the file, symbol, command or error it acts on, copied exactly from the transcript. "Continue the refactor" is unusable; "add the `--json` flag to `cli/report.py:build_parser`" can be acted on without re-reading anything.]
