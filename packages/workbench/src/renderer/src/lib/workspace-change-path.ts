function normalizeChangePath(path: string | undefined): string {
  return (path ?? '').replace(/\\/g, '/').trim().toLowerCase()
}

function pathsMatch(filePath: string, changePath: string): boolean {
  const file = normalizeChangePath(filePath)
  const change = normalizeChangePath(changePath)
  if (!file || !change) return false
  if (file === change) return true
  return file.endsWith(`/${change}`) || change.endsWith(`/${file}`)
}

export function lookupPatchForPath(
  patchMap: Map<string, string>,
  filePath: string
): string | undefined {
  const normalized = normalizeChangePath(filePath)
  if (!normalized) return undefined

  const direct = patchMap.get(normalized)
  if (direct) return direct

  for (const [key, patch] of patchMap) {
    if (pathsMatch(normalized, key)) return patch
  }
  return undefined
}

export function pathHasChanges(patchMap: Map<string, string>, filePath: string): boolean {
  return lookupPatchForPath(patchMap, filePath) !== undefined
}

export function directoryHasChanges(patchMap: Map<string, string>, directoryPath: string): boolean {
  const dir = normalizeChangePath(directoryPath)
  if (!dir) return false
  const prefix = `${dir}/`
  for (const key of patchMap.keys()) {
    if (key.startsWith(prefix) || pathsMatch(dir, key)) return true
  }
  return false
}

export { normalizeChangePath }
