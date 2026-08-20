# Cycle Handoff Briefing

You are about to cross a context cycle boundary. The conversation so far has
crossed the per-cycle token budget, so this entire transcript is going to be
**archived to disk** and the next turn will start with a fresh context: the
original system prompt, structured state (todos, plan, working set, open
sub-agents), the user's pending message, and a free-form briefing that **you
write right now**.

Your job, in this single message: produce a `<carry_forward>` block of at most
**3,000 tokens** that captures the irreducible state the *next cycle's you* will
need to continue without redoing work.

## What to put in `<carry_forward>`

Write concrete prose, not bullet-point summaries of the transcript. Cover:

- **Decisions made and why.** The things you've chosen and the reasoning that
  led there. Not "we discussed options" — name the choice and the constraint
  that made it the right one.
- **Constraints discovered.** Concrete facts about the codebase, environment,
  user preferences, or external systems that the next cycle will trip over if
  it doesn't know them. (e.g. "the audit log is JSONL not JSON", "the user
  insists on no `unwrap()` in non-test code", "macOS sandbox blocks raw
  sockets in tools/exec.rs".)
- **Hypotheses being tested.** Open questions you're actively investigating,
  what you're trying to falsify, what evidence would change your mind.
- **Approaches that failed.** Dead ends with enough detail that the next
  cycle won't repeat them. Name the approach and the specific reason it
  didn't work, not just "tried X, didn't work".
- **What you have not verified.** Anything you or an earlier turn claimed was
  done — tests "passing", a fix "working", a file "created" — without seeing the
  evidence. Say so plainly and mark it unverified. The next cycle cannot
  re-check the transcript for you; if this briefing states it as fact, it
  becomes fact, and the cycle builds on it.
- **What this cycle never established.** Context the next step depends on that
  was never actually confirmed here: a file referenced but not read, a schema or
  signature assumed but not inspected, a question you asked the user who has not
  answered. Naming the gap is what sends the next cycle to check it instead of
  assuming it.
- **Open questions for the user.** Things you're blocked on that the next
  cycle should ask about if the user doesn't volunteer them.
- **The next concrete action, anchored.** Name the file, symbol, command or
  error it acts on, copied exactly. "Continue the refactor" is unusable;
  "add the `--json` flag to `cli/report.py:build_parser`" can be acted on
  without re-reading anything. Then give the remaining sequence: what follows,
  in order, and the decisions you have already made for those steps so the next
  cycle does not reopen them. You hold more context on this task right now than
  you ever will again — whatever you settle here is one less thing to
  rediscover.

## What NOT to put in `<carry_forward>`

- Tool output bytes. (They're already archived to disk.)
- File contents you read. (The next cycle can re-read them — pricier than a
  briefing token, but cheaper than a wrong assumption built on a stale
  paraphrase.)
- Step-by-step recap of what you did. The next cycle does not need to know
  the order of operations; it needs to know the *current state*.
- Pleasantries, throat-clearing, framing language. Every token matters.

## Format

Open with `<carry_forward>` on its own line. Close with `</carry_forward>` on
its own line. No prose outside the tags. No nested tags. No code fences around
the block itself (you can use code fences inside if you need to quote a
specific snippet).

There is no archive-recall tool in the next cycle — put every load-bearing
fact into `<carry_forward>` itself. Prefer a precise briefing over a sparse
one that the next cycle cannot recover.

## Example shape (do not copy verbatim — write your own)

```
<carry_forward>
Working on issue #124 (cycle-restart). Key decisions: (1) trigger at 110K
tokens not 128K — need ~8.5K headroom for the briefing turn itself plus
next-turn growth before the next boundary; (2) archive to JSONL with a
header line so future tools can stream-read without parsing the whole
file. Constraint discovered: the provider's thinking mode requires
reasoning_content replay on assistant messages with tool calls — so seed
messages can't include orphan tool calls from the archived cycle. The
approach of "summarize then keep recent messages" (the old compaction
path) was failing because the model couldn't tell which fragments were
verbatim vs. paraphrased; replacing it entirely. Open question for user:
do they want per-model briefing token caps, or one global cap?
</carry_forward>
```

Now write your `<carry_forward>` for this conversation.
