## Compaction Handoff

You are about to run out of context. Write a handoff note to yourself so you can continue this task seamlessly after the older messages are archived.

Write it as your own continuing train of thought — first person, present tense, the way you would reason through the next move. Not a third-party report about someone else's work. Write it in the language the session has been using; do not switch to English because these instructions are in English.

The next turn will see: this note inside `<archived_context>`, the user's requests quoted verbatim in `<prior_user_requests>`, and a few recent verbatim messages. It will **not** see the archived tool outputs — so anything you do not carry here is gone unless it can be re-derived from disk.

Two headings are required, because the runtime checks for them: `### Goal` and `### Next step`. The others below are the shape that usually fits a coding session — use the ones that carry something and drop the ones that do not. Do not keep a heading just to write `None` under it, and add a heading of your own where the work calls for one. Let the shape follow the task: a long multi-step session warrants detail, a nearly finished one needs a few lines.

Output **only** Markdown. Do not call tools, do not wrap the output in XML, do not add a preamble or closing remarks. Preserve exact file paths, commands, errors, and decisions; abbreviate repetitive tool dumps. Be honest about uncertainty — this note is worth less than nothing if it reads more confident than the work was.

Two rules about who said what:

- The transcript labels each line `User:`, `Assistant:` or `Harness:`. Only `User:` lines are the human. `Harness:` lines are automated injections from the runtime, and `Assistant:` lines may *quote or paraphrase* the user — neither is evidence the user said anything. Never turn them into a user request or a user constraint. If you are unsure who wanted something, describe it as a decision, not as a user instruction.
- The user's own requests are carried verbatim in a separate block and do not depend on you. Do not spend this note re-paraphrasing them. Spend it on what cannot be recovered any other way: what was tried, what it produced, what was decided, and why.

If the session is executing an approved plan, the plan file is the source of truth — do not restate its full body. In **Key Decisions** keep settled choices that are not already obvious from that file. In **In Progress** / **Next step** write the forward plan: what remains, in order, and the next concrete action. Preserve the plan file path if the transcript named one, so the next turn can re-read it.

### Goal
[What I am trying to accomplish in this session — the user's objective, in my own words]

### Constraints
[What bounds the work. Two kinds, both needed:
- stated: what the user ruled out or asked not to touch
- discovered: what the work revealed — a version pin, a flaky test, an API that rejects a value, a command that must run from a specific directory
Quote discovered constraints in the exact words of the error or output that established them. A paraphrased constraint gets re-litigated; a quoted one does not.]

### Progress

#### Done
[What is complete and verified — landed commits, passing tests, shipped patches.
Verified means I saw the evidence, not that a step claimed success. If an earlier
turn asserted something was done — tests "passing", a fix "working", a file
"created" — but nothing in the transcript confirms it, record it as unverified
and say so in those words. An unverified claim recorded as fact is the one error
this note cannot recover from: the next turn will build on it.]

#### In Progress
[What is mid-flight — partial implementations, open PRs, work-in-tree]

#### Blocked
[What is stuck, why, and what would unblock it]

### Unknowns
[What my next step depends on that this session never established. Files or
paths referenced but never read, a schema or signature assumed but never
inspected, a question I put to the user and they have not answered, a behaviour
I inferred from naming rather than from code. Name each gap concretely enough
that I go and check it instead of assuming it. This is the section most worth
keeping even when short — an assumption I replay as fact is how the next turn
builds on sand.]

### Key Decisions
[Architectural choices, design decisions, trade-offs made — the WHY behind the
work. Keep what I have settled separate from what is still open, so the next turn
neither reopens a closed decision nor treats an undecided one as settled.]

### Next step
[Open with the single next action, anchored: name the file, symbol, command or error it acts on, copied exactly from the transcript. "Continue the refactor" is unusable; "add the `--json` flag to `cli/report.py:build_parser`" can be acted on without re-reading anything.

Then keep going — this is the moment to invest in the plan. Right now I hold more
context on this task than I ever will again, and the next turn resumes with less,
so the plan I commit here is the one it will follow. Set out the remaining steps
in order, the decisions I have already made for them (so the next turn does not
reopen them), the obstacles I can already foresee and how I mean to handle them,
and any work I can settle now — the exact patch, query, or shape of the final
answer I already know I will produce. Anything I settle here is one less thing
the next turn must rediscover.]
