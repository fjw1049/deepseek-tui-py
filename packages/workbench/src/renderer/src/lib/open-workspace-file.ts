import { openWorkspacePathInEditor, type WorkspacePathTarget } from './open-workspace-path'

export function uniqueWorkspaceRoots(...roots: Array<string | undefined>): string[] {
  const seen = new Set<string>()
  const unique: string[] = []
  for (const root of roots) {
    const trimmed = root?.trim() ?? ''
    if (!trimmed) continue
    const key = trimmed.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(trimmed)
  }
  return unique
}

export async function canOpenWorkspaceFileInApp(
  path: string,
  workspaceRoot?: string
): Promise<boolean> {
  const root = workspaceRoot?.trim() ?? ''
  if (!root || !path.trim()) return false
  if (typeof window.dsGui?.resolveWorkspaceFile !== 'function') return false
  try {
    const result = await window.dsGui.resolveWorkspaceFile({
      path,
      workspaceRoot: root
    })
    return result.ok
  } catch {
    return false
  }
}

export async function openWorkspaceFilePreferInApp(
  target: WorkspacePathTarget,
  workspaceRoot: string | string[] | undefined,
  openInApp: (
    path: string,
    root: string,
    line?: number,
    column?: number
  ) => Promise<boolean>,
  externalRoots?: string[]
): Promise<'in-app' | 'external'> {
  const roots = uniqueWorkspaceRoots(
    ...(Array.isArray(workspaceRoot) ? workspaceRoot : [workspaceRoot])
  )
  for (const root of roots) {
    if (!(await canOpenWorkspaceFileInApp(target.path, root))) continue
    const opened = await openInApp(target.path, root, target.line, target.column)
    if (opened) return 'in-app'
  }
  const searchRoots = uniqueWorkspaceRoots(...(externalRoots ?? []), ...roots)
  await openWorkspacePathInEditor(target, searchRoots[0], {
    allowOutsideWorkspace: true,
    searchRoots
  })
  return 'external'
}
