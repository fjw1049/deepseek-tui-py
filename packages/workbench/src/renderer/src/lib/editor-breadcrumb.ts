import { formatFilePathForDisplay } from './diff-stats'
import { workspaceLabelFromPath } from './workspace-label'

export function splitFileNameAndParent(path: string): { name: string; parent: string } {
  const normalized = path.replace(/\\/g, '/').replace(/\/+$/, '')
  const slash = normalized.lastIndexOf('/')
  if (slash < 0) return { name: normalized || path, parent: '' }
  return { name: normalized.slice(slash + 1), parent: normalized.slice(0, slash) }
}

/** project › dirs › file. Collapse middle folders to a single ellipsis — never clip a segment to "s…". */
export function breadcrumbSegments(
  path: string,
  workspaceRoot: string
): string[] {
  const project =
    workspaceLabelFromPath(workspaceRoot) ||
    workspaceRoot.replace(/\\/g, '/').split('/').filter(Boolean).pop() ||
    workspaceRoot
  const relative = formatFilePathForDisplay(path, workspaceRoot) ?? path
  const parts = relative.replace(/\\/g, '/').split('/').filter(Boolean)
  if (parts.length === 0) return [project]
  return [project, ...parts]
}

export function collapseBreadcrumbSegments(segments: string[]): string[] {
  if (segments.length <= 4) return segments
  return [segments[0]!, '…', segments[segments.length - 2]!, segments[segments.length - 1]!]
}
