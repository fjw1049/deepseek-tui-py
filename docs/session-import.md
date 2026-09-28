# Importing Codex and Claude Code sessions

Settings → Import copies selected conversations into the native thread store. No model turn,
source resume, fork, or tool execution is requested. Source transcripts and project files are
not modified. Reading local Codex history starts its installed app-server, which can maintain
its own operational metadata; this is not a filesystem-wide read-only guarantee.

## Reading the source of truth

For the current local Codex home, prefer the installed desktop runtime (then the PATH CLI).
Use only `initialize`, `thread/read`, and `thread/turns/list`. Request `itemsView: full`, follow
all cursors in ascending order, and retain native turn/item IDs. Reject partial views, repeated
cursors, duplicate turns, active conversations, and metadata changes during pagination. Calls
have a 30-second timeout; a conversation has a 120-second pagination deadline. No partial page
sequence is committed. If the runtime explicitly reports an unsupported pagination method,
use the offline reader and display a warning. Other runtime failures are reported, not hidden.
Protocol reference: https://learn.chatgpt.com/docs/app-server

For offline Codex directories, or when no runtime is installed:

- Use the state database's `rollout_path` to identify the current history. Copied directories
  can relocate that exact file by its filename. Without an index, require one unambiguous head.
- Follow `history_base.thread_id` to the referenced rollout storage UUID. Recursively inherit
  only records before `end_ordinal_exclusive`, validating `end_byte_offset` as well.
- Never concatenate files by logical session ID or modification time. Unselected branches and
  excluded ancestor tails are not part of the current conversation. Exact duplicate files may
  represent the same source; conflicting candidates, missing ancestors, cycles, and inconsistent
  boundaries fail the session instead of producing a partial success.
- Use completed UI items per turn, falling back to response items for legacy turns. Source
  files changing during the read are rejected. Subagent-only and empty sessions are skipped.

For Claude Code, follow the selected leaf's `parentUuid` / `logicalParentUuid` chain. A final
`last-prompt` leaf selects its branch; subsequent messages continue it. Missing ancestors and
cycles fail instead of silently importing a suffix. Preserve block order and distinct block
UUIDs. Pair tool results with their calls; retain unmatched results as inert historical records
with a warning. Sidechains and subagent files are excluded.

## User flow and limitations

1. Select sources and scan. Defaults respect `CODEX_HOME` and `CLAUDE_CONFIG_DIR`, otherwise
   `~/.codex` and `~/.claude`. Custom source directories use offline reading.
2. Search, filter archived conversations, and select visible sessions. Sessions with changed or
   older imported snapshots are marked as available for an update/correction.
3. Keep the project folder or link its current location. Missing project directories allow
   history-only import; link a valid directory before continuing work.
4. Import sequentially. A session failure does not stop other sessions. Retry failures or stop
   after the current session. Leaving settings stops after the current request completes.

Copy text, readable reasoning and available tool records. Attachments remain placeholders.
Encrypted reasoning, unrelated branches, source approvals, credentials, background jobs and
file rollback checkpoints are not restored. Continue with this application's model and tools;
historical tool records remain inert evidence. Source usage is not counted as local model usage.
Native Codex turn boundaries are preserved, including multiple user items within one turn.
Offline timestamps retain source order, using microsecond adjustments where necessary.

## Snapshot updates and recovery

`POST /v1/external-sessions/scan` accepts `source` and optional `root`.
`POST /v1/external-sessions/import` also accepts `path`, `session_id`, and optional `workspace`.
Results distinguish `imported`, `updated`, `linked`, and `skipped`.

A source/session identity maps to one native thread. An unchanged, intact snapshot is skipped.
Updating first backs up the existing imported thread/turn/item records under
`threads/import_backups/<thread-id>/<timestamp>/`. The response includes `backup_path`.

Write new items and turns into a distinct generation, then atomically publish that generation
in the thread record. Unpublished and superseded generations are excluded from thread history
and sidebar counts, including after a crash. Failed writes leave the prior snapshot visible.
Cleanup of superseded records happens after commit; the backup remains available. Native
follow-up turns, project association and user settings are preserved. This supports correcting
older import bugs and source rewinds, not just appending a matching prefix.

Mutations use the native thread lease and store lock. Source paths are confined to the chosen
root. Offline limits are 256 MB per file and 16 MB per record; native response pages are capped
at 64 MB. History-only records remain linkable after their source files are removed.

## Verification

- `pytest tests/contract/test_external_sessions.py tests/contract/test_codex_history.py tests/contract/test_thread_store_fault_tolerance.py`
- Workbench: `npm test -- src/renderer/src/components/settings/SessionImportPanel.test.ts`

Regression coverage includes ancestry cutoffs, index-selected branches, ambiguous histories,
missing ancestors, Claude block order/cycles, full pagination, source changes, snapshot backups,
failed-write recovery, invisible staged generations, repeat import, native follow-up retention,
directory relinking and batch retry/stop. Real-source validation compares the offline reader's
messages against the native API, rather than comparing a parser only against its own output.
