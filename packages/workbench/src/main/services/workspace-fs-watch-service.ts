/**
 * Recursive workspace file watching backing git-state freshness.
 *
 * The renderer's git panels otherwise refresh only on agent events
 * (workspaceDirtyTick bumps from SSE), so edits made by external editors
 * (Cursor, VS Code, plain saves) or long-running shell commands would never
 * show up until the next agent action. One watcher per renderer
 * (WebContents); raw fs events are debounced (quiet window + max wait) and
 * pushed as `workspace:fs-changed`.
 */
import { watch, statSync, type FSWatcher } from 'node:fs'
import path from 'node:path'
import type { WebContents } from 'electron'

const QUIET_MS = 300
const MAX_WAIT_MS = 1500

// Churn-heavy directories that never affect the git panels. Missing an
// event here is benign (the next agent event still refreshes), so the list
// errs on the side of fewer wakeups rather than completeness.
const IGNORED_SEGMENTS = new Set([
  'node_modules',
  '.venv',
  'venv',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.cache',
  '.next',
  'dist',
  'out',
  'build',
  '.DS_Store'
])

type WatchEntry = {
  root: string
  watcher: FSWatcher
  quietTimer: NodeJS.Timeout | null
  maxWaitTimer: NodeJS.Timeout | null
}

const entries = new Map<number, WatchEntry>()
// Senders that already have a destroyed-cleanup hook (avoid stacking one
// listener per re-watch when the active workspace changes).
const destroyedHooked = new WeakSet<WebContents>()

function isRelevant(rel: string): boolean {
  const norm = rel.split(path.sep).join('/')
  if (norm === '.git') return false
  if (norm.startsWith('.git/')) {
    // Inside .git only ref movement matters (commit, checkout, merge).
    // Notably NOT .git/index: plain `git status` rewrites it, which would
    // loop with the refresh this watcher triggers.
    return norm === '.git/HEAD' || norm.startsWith('.git/refs/')
  }
  for (const segment of norm.split('/')) {
    if (IGNORED_SEGMENTS.has(segment)) return false
    if (segment.endsWith('.swp') || segment.endsWith('~')) return false
  }
  return true
}

function stopEntry(entry: WatchEntry): void {
  if (entry.quietTimer) clearTimeout(entry.quietTimer)
  if (entry.maxWaitTimer) clearTimeout(entry.maxWaitTimer)
  try {
    entry.watcher.close()
  } catch {
    // Watcher already dead — nothing to release.
  }
}

/** Watch `workspaceRoot` for `sender`, replacing any previous watch. */
export function watchWorkspaceFs(sender: WebContents, workspaceRoot: string): boolean {
  unwatchWorkspaceFs(sender)
  const root = workspaceRoot.trim()
  if (!root) return false
  try {
    if (!statSync(root).isDirectory()) return false
  } catch {
    return false
  }

  const senderId = sender.id
  const fire = (): void => {
    const entry = entries.get(senderId)
    if (!entry) return
    if (entry.quietTimer) clearTimeout(entry.quietTimer)
    if (entry.maxWaitTimer) clearTimeout(entry.maxWaitTimer)
    entry.quietTimer = null
    entry.maxWaitTimer = null
    if (sender.isDestroyed()) {
      stopEntry(entry)
      entries.delete(senderId)
      return
    }
    sender.send('workspace:fs-changed', { root: entry.root })
  }

  let watcher: FSWatcher
  try {
    watcher = watch(root, { recursive: true, persistent: false }, (_event, filename) => {
      const rel = typeof filename === 'string' ? filename : ''
      if (rel && !isRelevant(rel)) return
      const entry = entries.get(senderId)
      if (!entry) return
      // Trailing debounce with a max wait so a steady stream of events
      // (builds, bulk saves) cannot postpone the refresh forever.
      if (entry.quietTimer) clearTimeout(entry.quietTimer)
      entry.quietTimer = setTimeout(fire, QUIET_MS)
      if (!entry.maxWaitTimer) entry.maxWaitTimer = setTimeout(fire, MAX_WAIT_MS)
    })
  } catch {
    return false
  }
  watcher.on('error', () => {
    const entry = entries.get(senderId)
    if (entry) {
      stopEntry(entry)
      entries.delete(senderId)
    }
  })

  entries.set(sender.id, { root, watcher, quietTimer: null, maxWaitTimer: null })
  if (!destroyedHooked.has(sender)) {
    destroyedHooked.add(sender)
    const senderId = sender.id
    sender.once('destroyed', () => {
      const entry = entries.get(senderId)
      if (entry) {
        stopEntry(entry)
        entries.delete(senderId)
      }
    })
  }
  return true
}

export function unwatchWorkspaceFs(sender: WebContents): void {
  const entry = entries.get(sender.id)
  if (!entry) return
  stopEntry(entry)
  entries.delete(sender.id)
}
