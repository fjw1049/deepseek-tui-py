# ADR 0001: Attribute Task Worktree Changes to a Durable Baseline

- Status: Accepted
- Date: 2026-08-30

## Context

Each task runs in a hidden Git worktree while the project working tree remains
the canonical user workspace. The project may already contain staged,
unstaged, or untracked changes when a task starts.

Git status alone cannot identify ownership. Project changes copied into a task
worktree remain dirty relative to Git `HEAD`; treating all dirty worktree paths
as task output produces false recovery prompts and can overwrite newer project
changes.

## Decision

For every managed task worktree, persist a baseline `B` after a successful
project-to-task sync. The baseline contains:

- the worktree `HEAD`;
- every path that differs from `HEAD`;
- a signature of each path's content, type, and mode.

Let `P` be the current project and `T` the current task worktree:

- If `T == B`, the task has no unrecorded changes. Refresh it from `P`
  silently, including project dirty and untracked files.
- If a turn checkpoint records `T - B`, publish that checkpoint with the
  existing three-way merge. Only an unmergeable path is a user-facing conflict.
- If `T != B` without a checkpoint, preserve both copies and enter recovery.
  Recovery may act only on the paths in `T - B`, never on all dirty paths.
- After publish, conflict resolution, or code rollback, resync the task
  worktree and atomically record a new baseline.
- Before a multi-file inbound sync mutates the task copy, persist a sync
  journal containing the source/target commits and each path's before/target
  signature. A restart may complete the sync only when every path is still in
  one of those two states; a third state enters recovery instead of guessing
  ownership.
- Bind a recovery confirmation to signatures of the exact `T - B` bytes shown
  to the user. If either the path set or any bytes change before confirmation,
  refresh the choice without writing anything.
- Before the first project write, stage the project root and the checkpoint's
  immutable pre/post images in a publication journal. Mark the project apply
  complete only after every write succeeds, and retain the pending publication
  until the task copy and its new baseline are durable. A restart retries an
  incomplete apply, skips an already-complete apply, and never reconstructs a
  preimage from bytes it may already have written.
- Bind every checkpoint to signatures of the exact task bytes it captured.
  Recheck those signatures before and during publication, so a late background
  edit cannot be silently included in an earlier turn.
- Restore a checkpoint with compare-and-swap semantics: verify the whole plan,
  recheck each path immediately before writing, verify after each write, and
  undo only bytes that are still ours. Content, type, and executable mode are
  all part of that decision.
- If an existing task worktree disappears, retain its exact association and
  enter the missing state until that path returns. If initial Git isolation
  cannot be created, fail the task preparation instead of silently writing in
  the project checkout.
- Automatic cleanup uses Git's final clean-worktree check without force. A
  file arriving between inspection and removal keeps the task copy; force is
  reserved for an explicit user-authorized discard.
- A persisted recovery marker is evidence to re-check, not a permanent source
  of truth. If the baseline proves that the task has no unrecorded changes, the
  marker clears automatically.

Worktrees created before this ADR have no baseline. They may self-heal only
when every dirty path in the task is byte-identical to the project and the task
commit is reachable from the project. Ambiguous legacy state remains protected.

## User-facing states

Normal sync stays invisible. The UI interrupts only for:

- a real file merge conflict, with concrete paths;
- a failed automatic sync, with retry;
- verified uncheckpointed task paths, with a file list and confirmation;
- a missing task worktree, shown as workspace loss with a safe recheck action
  rather than as a fake file.

The reason is stored separately from conflicting file paths, so every legal
repository filename remains representable. Files explicitly copied through
`.worktreeinclude` participate in the same baseline rules even though Git
normally hides ignored files from status output. Ignored files not selected by
that policy remain outside the managed delivery contract.

Conversation rewind and code rollback are independent choices. A successful
code rollback must refresh the hidden worktree before another warmup can run.

## Invariants

1. A task that changed no files never shows a code-recovery prompt.
2. New project changes never become task-owned merely because they were copied
   into a hidden worktree.
3. Recovery never applies or discards paths outside `T - B`.
4. Publish followed by rollback cannot restore the published version again.
5. An empty task with pending, blocked, failed, or recovery state is not reused
   as a new task.
6. Project writes are serialized across processes on POSIX and Windows.
7. A crash or cancellation cannot turn a partial sync into task-owned labor.
8. Symlinks and filesystem modes are handled as path identity (or left
   unresolved), never followed by text publish or rollback code.
