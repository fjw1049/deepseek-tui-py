import type { NormalizedThread } from '../agent/types'
import { isWorkspaceHidden } from './sidebar-chrome'
import { isClawWorkspacePath, normalizeWorkspaceRoot } from './workspace-path'

export type ActivityStatus = 'waiting' | 'failed' | 'running' | 'unread'
export type ActivityGroup = 'attention' | 'running' | 'unread'
export type ActivityRow = { thread: NormalizedThread; status: ActivityStatus; unread: boolean }
export type ActivityGroups = Record<ActivityGroup, ActivityRow[]>

export function buildSidebarActivity(input: {
  threads: readonly NormalizedThread[]
  hiddenWorkspacePaths: readonly string[]
  runningIds: ReadonlySet<string>
  unreadThreadIds: Readonly<Record<string, boolean>>
  activeThreadId: string | null
  activeWaiting: boolean
}): ActivityGroups {
  const groups: ActivityGroups = { attention: [], running: [], unread: [] }
  for (const thread of input.threads) {
    if (thread.archived || isClawWorkspacePath(thread.workspace) ||
      isWorkspaceHidden(normalizeWorkspaceRoot(thread.workspace), input.hiddenWorkspacePaths)) continue
    const unread = input.unreadThreadIds[thread.id] === true && thread.id !== input.activeThreadId
    const turnStatus = thread.latestTurnStatus ?? thread.status
    const waiting = thread.id === input.activeThreadId ? input.activeWaiting || thread.activityWaiting : thread.activityWaiting
    const running = input.runningIds.has(thread.id) || ['running', 'queued', 'in_progress'].includes(turnStatus ?? '')
    const blocked = thread.publishBlocked || (thread.publishConflicts?.length ?? 0) > 0
    const failed = turnStatus === 'failed' || thread.latestTurnFailed
    // A new live turn supersedes a previous failure; unread is an independent badge.
    const status: ActivityStatus | null = waiting ? 'waiting' : running ? 'running' : blocked || failed ? 'failed' : unread ? 'unread' : null
    if (!status) continue
    groups[status === 'waiting' || status === 'failed' ? 'attention' : status].push({ thread, status, unread })
  }
  for (const rows of Object.values(groups)) {
    rows.sort((a, b) => {
      const time = (thread: NormalizedThread): number => Date.parse(thread.activityAt ?? thread.createdAt ?? thread.updatedAt) || 0
      return time(b.thread) - time(a.thread) || a.thread.id.localeCompare(b.thread.id)
    })
  }
  return groups
}

const DISMISSED_ACTIVITY_KEY = 'deepseekgui.sidebar.dismissedActivity'

export function activityDismissalKey({ thread, status }: ActivityRow): string {
  // updatedAt changes during background refreshes; a turn and its status identify the reminder.
  return JSON.stringify([thread.latestTurnId ?? thread.activityAt ?? thread.createdAt ?? '', status,
    thread.publishBlocked ?? false, thread.publishConflicts ?? []])
}

export function loadDismissedActivity(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(DISMISSED_ACTIVITY_KEY) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(Object.entries(value).filter(([, key]) => typeof key === 'string'))
  } catch { return {} }
}

export function persistDismissedActivity(value: Record<string, string>): void {
  try { window.localStorage.setItem(DISMISSED_ACTIVITY_KEY, JSON.stringify(value)) }
  catch { /* Dismissal still works for this session when storage is unavailable. */ }
}

export function filterDismissedActivity(groups: ActivityGroups, dismissed: Readonly<Record<string, string>>): ActivityGroups {
  const visible = { ...groups }
  for (const group of ['attention', 'running', 'unread'] as const) {
    visible[group] = groups[group].filter((row) => dismissed[row.thread.id] !== activityDismissalKey(row))
  }
  return visible
}
