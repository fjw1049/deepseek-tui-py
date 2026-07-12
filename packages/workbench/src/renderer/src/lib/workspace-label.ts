import i18n from '../i18n'
import { isDefaultWorkspaceRoot } from '@shared/workspace-defaults'

function isDefaultWorkspacePath(path: string): boolean {
  return isDefaultWorkspaceRoot(path)
}

/** Hide generic default workspace path in compact chrome (e.g. top bar). */
export function shouldShowWorkspaceInHeader(path: string): boolean {
  const p = path?.trim() ?? ''
  return Boolean(p) && !isDefaultWorkspacePath(p)
}

export function workspaceLabelFromPath(path: string): string {
  const p = path?.trim() ?? ''
  if (!p) return i18n.t('common:workingDirectory')
  if (isDefaultWorkspacePath(p)) return i18n.t('common:workingDirectory')
  const normalized = p.replace(/[/\\]+$/, '')
  const parts = normalized.split(/[/\\]/)
  const base = parts[parts.length - 1]
  return base || i18n.t('common:workingDirectory')
}

/**
 * Terminal tabs show the concrete directory name even for the default
 * workspace (so temporary chats read "default_workspace" instead of the
 * generic "工作目录" used in compact chrome). Falls back to the generic title
 * only when there is no path at all.
 */
export function terminalLabelFromPath(path: string): string {
  const p = path?.trim() ?? ''
  if (!p) return i18n.t('common:workingDirectory')
  const normalized = p.replace(/[/\\]+$/, '')
  const parts = normalized.split(/[/\\]/)
  const base = parts[parts.length - 1]
  return base || i18n.t('common:workingDirectory')
}
