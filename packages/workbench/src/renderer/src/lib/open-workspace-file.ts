import type { WorkspacePathTarget } from './open-workspace-path'

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

function normalizePathKey(value: string): string {
  return value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

/** Prefer the workspace root that already contains an absolute file path. */
export function orderRootsForPath(path: string, roots: string[]): string[] {
  const target = normalizePathKey(path)
  if (!target.startsWith('/') && !/^[a-z]:\//.test(target)) return roots
  const containing: string[] = []
  const rest: string[] = []
  for (const root of roots) {
    const key = normalizePathKey(root)
    if (target === key || target.startsWith(`${key}/`)) containing.push(root)
    else rest.push(root)
  }
  containing.sort((left, right) => right.length - left.length)
  return [...containing, ...rest]
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
): Promise<'in-app' | 'none'> {
  const roots = orderRootsForPath(
    target.path,
    uniqueWorkspaceRoots(
      ...(Array.isArray(workspaceRoot) ? workspaceRoot : [workspaceRoot])
    )
  )
  for (const root of roots) {
    const opened = await openInApp(target.path, root, target.line, target.column)
    if (opened) return 'in-app'
  }
  return 'none'
}
