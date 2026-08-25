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

export async function openWorkspaceFilePreferInApp(
  target: WorkspacePathTarget,
  workspaceRoot: string | string[] | undefined,
  openInApp: (
    path: string,
    root: string,
    line?: number,
    column?: number
  ) => Promise<boolean>
): Promise<'in-app' | 'external'> {
  const roots = uniqueWorkspaceRoots(
    ...(Array.isArray(workspaceRoot) ? workspaceRoot : [workspaceRoot])
  )
  for (const root of roots) {
    const opened = await openInApp(target.path, root, target.line, target.column)
    if (opened) return 'in-app'
  }
  await openWorkspacePathInEditor(target, roots[0])
  return 'external'
}
