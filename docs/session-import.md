# Importing Codex and Claude Code sessions

Settings → Import scans local logs and copies selected conversations into the native thread store.
No Codex/Claude process or model API is invoked. Source logs and project files are never written.

## User flow

1. Select Codex and/or Claude Code and scan. Defaults respect `CODEX_HOME` and
   `CLAUDE_CONFIG_DIR`, falling back to `~/.codex` and `~/.claude`.
2. Optionally choose a copied source directory. Codex home, sessions and archived_sessions
   directories and Claude home/projects/project directories are supported.
3. Search projects or titles, optionally include archived sessions, and select projects or
   individual sessions. Selection applies to visible sessions only.
4. Keep the existing project folder or select its new location. Missing folders do not block
   history import: those conversations are read-only until linked in Settings → Import.
5. Import sequentially with progress. A failed session does not stop the batch. Retry failed
   sessions or stop after the current one. Leaving the page also stops after the current session.

Imported conversations use this application's configured provider/model. The source model,
source identity and historical workspace are retained separately. They do not restore source
credentials, permissions, background processes, pending approvals, or file rollback checkpoints.

## Format and continuation rules

- Codex: use completed UI items when available; use response items for older logs. Never append
  both representations. Optional read-only SQLite/session-index metadata supplies titles and
  archive state. Subagent-only logs and empty sessions are skipped.
- Claude Code: follow the current leaf's parent chain, including logical parents across
  compaction. Keep distinct block UUIDs even when their API message IDs match. Tool results in
  user-role records remain tool output, not new user turns. Sidechains/subagent files are excluded.
- Text, readable reasoning, and available tool details are copied. Attachments are represented
  by placeholders, not copied. Encrypted reasoning, alternate branches and proprietary records
  are not reconstructed; conversion warnings are shown for each session.
- For continuation, external tool entries become bounded historical text, not foreign tool-call
  messages. A reminder tells the model to use current tools and verify current project files.
- Source timestamps are preserved on items. Turn sort timestamps advance by microseconds only
  when necessary to retain source ordering for equal or regressing timestamps.

## Persistence and failure handling

`POST /v1/external-sessions/scan` accepts `source` (`codex` or `claude`) and optional `root`.
It returns grouped-UI metadata, conversion warnings, skipped auxiliary-log count, and file errors.
It never creates threads or invokes a model.

`POST /v1/external-sessions/import` additionally accepts `path`, `session_id`, and optional
`workspace`. One request commits one session; responses distinguish `imported`, `linked`, and
`skipped`. Existing imports are snapshots: reimport does not overwrite later native conversation
history or append source updates. A deterministic source/session identity prevents duplicate
imports, including after a disconnected request or restart. Deleted native imports can be
imported again. History-only imports remain linkable even after their source logs are deleted.

The importer validates that new sessions are under the scanned source root. Reads freeze the
file's initial byte length, tolerate an incomplete final record, and reject corrupt middle records.
Limits are 256 MB per source file and 16 MB per JSONL record. Mutations use the native thread lease
and store lock; items and turns are written before the discoverable thread, with rollback on
failure. Source timestamps/model usage do not count as new local model usage.

## Checks

- `pytest tests/contract/test_external_sessions.py`
- Workbench: `npm test -- src/renderer/src/components/settings/SessionImportPanel.test.ts`

These cover duplicate representations, Claude branches and blocks, inert tool history,
repeat imports, rollback/retry, active-file tails, archive filtering, directory relinking,
source-order preservation, batch failure recovery, and stopping after an in-flight session.
