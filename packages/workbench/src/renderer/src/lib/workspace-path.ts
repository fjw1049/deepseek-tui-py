import { isDefaultWorkspaceRoot } from '@shared/workspace-defaults'

function normalizePathForMatch(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function isInternalTemporaryWorkspace(path?: string): boolean {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return false
  const normalized = normalizePathForMatch(trimmed)
  return (
    /\/deepseek-tui-updates\/tmp(?:\/|$)/.test(normalized)
    || normalized === '/tmp'
    || normalized.startsWith('/tmp/')
    || normalized === '/private/tmp'
    || normalized.startsWith('/private/tmp/')
    || /^\/var\/folders\/[^/]+\/[^/]+\/t(?:\/|$)/.test(normalized)
    || /^\/private\/var\/folders\/[^/]+\/[^/]+\/t(?:\/|$)/.test(normalized)
    || /\/appdata\/local\/temp(?:\/|$)/.test(normalized)
  )
}

export function isChatsWorkspace(path?: string): boolean {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return true
  if (isInternalTemporaryWorkspace(trimmed)) return true
  return isDefaultWorkspaceRoot(trimmed)
}

export function isClawWorkspacePath(path?: string): boolean {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return false
  const normalized = normalizePathForMatch(trimmed)
  return (
    normalized.includes('/.deepseek/claw/') ||
    normalized.includes('/.deepseek/workbench/claw/') || // legacy (pre-flat)
    normalized.includes('/.deepseekgui/claw/') // legacy
  )
}

export function normalizeWorkspaceRoot(path?: string | null): string {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return ''
  if (isInternalTemporaryWorkspace(trimmed)) return ''
  return trimmed
}

export type ThreadPathFields = {
  id: string
  workspace?: string
  envMode?: 'local' | 'worktree'
  worktreePath?: string | null
}

export function resolveActiveThreadWorkspace(
  activeThreadId: string | null | undefined,
  threads: ReadonlyArray<ThreadPathFields>,
  fallbackWorkspaceRoot?: string | null
): string {
  const activeThreadWorkspace = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)?.workspace
    : undefined
  return normalizeWorkspaceRoot(activeThreadWorkspace) || normalizeWorkspaceRoot(fallbackWorkspaceRoot)
}

/**
 * Absolute filesystem root for the active thread — including temporary
 * workspaces under /tmp. Unlike {@link resolveActiveThreadWorkspace}, this
 * does NOT blank out internal temp dirs; file preview / read / write need
 * the real path the runtime used when creating the thread.
 *
 * Always the project checkout. Hidden isolate copies are not shown in the UI.
 */
export function resolveThreadFilesystemRoot(
  activeThreadId: string | null | undefined,
  threads: ReadonlyArray<ThreadPathFields>,
  fallbackWorkspaceRoot?: string | null
): string {
  const thread = activeThreadId
    ? threads.find((item) => item.id === activeThreadId)
    : undefined
  const fromThread = thread?.workspace?.trim() ?? ''
  if (fromThread) return fromThread
  return fallbackWorkspaceRoot?.trim() ?? ''
}

/**
 * Git root for the branch the active task is actually changing.
 *
 * Managed worktrees stay invisible in product language, but their branch is
 * still the authoritative source for Branch diff, staging, commit and push.
 * Falling back to the project checkout keeps local-mode tasks conventional.
 */
export function resolveThreadGitRoot(
  activeThreadId: string | null | undefined,
  threads: ReadonlyArray<ThreadPathFields>,
  fallbackWorkspaceRoot?: string | null
): string {
  const thread = activeThreadId
    ? threads.find((item) => item.id === activeThreadId)
    : undefined
  const managedBranchRoot = thread?.envMode === 'worktree'
    ? thread.worktreePath?.trim() ?? ''
    : ''
  if (managedBranchRoot) return managedBranchRoot
  return resolveThreadFilesystemRoot(activeThreadId, threads, fallbackWorkspaceRoot)
}
