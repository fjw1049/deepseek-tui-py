## Compaction Handoff

You are writing a handoff for the *same* coding session after older messages are archived.
The continuing assistant will see: this summary inside `<archived_context>`, plus a few recent verbatim messages.
It will **not** see the full archived tool outputs. Write enough to continue seamlessly.

Output **only** Markdown with these headings (in this order). Keep every heading even if a section is empty — write `None` or `（无）` then.
Do not call tools. Do not wrap the output in XML. Do not add a preamble or closing remarks.
Preserve exact file paths, commands, errors, and decisions. Abbreviate repetitive tool dumps.

### Goal
[The user's high-level objective for this session]

### Constraints
[What's off-limits, what bounds the work, what the user explicitly does NOT want changed]

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
[The single next action to take when resuming — one line, concrete]
