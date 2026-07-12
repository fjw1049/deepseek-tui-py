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
  return normalized.includes('/.deepseekgui/claw/')
}

export function normalizeWorkspaceRoot(path?: string): string {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return ''
  if (isInternalTemporaryWorkspace(trimmed)) return ''
  return trimmed
}

export function resolveActiveThreadWorkspace(
  activeThreadId: string | null | undefined,
  threads: ReadonlyArray<{ id: string; workspace?: string }>,
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
 */
export function resolveThreadFilesystemRoot(
  activeThreadId: string | null | undefined,
  threads: ReadonlyArray<{ id: string; workspace?: string }>,
  fallbackWorkspaceRoot?: string | null
): string {
  const activeThreadWorkspace = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)?.workspace
    : undefined
  const fromThread = activeThreadWorkspace?.trim() ?? ''
  if (fromThread) return fromThread
  return fallbackWorkspaceRoot?.trim() ?? ''
}
