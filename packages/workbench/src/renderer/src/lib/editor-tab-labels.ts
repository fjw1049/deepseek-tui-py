/** Only repeated basenames need a label; use their shortest distinct parent suffix. */
export function editorTabParentLabels(paths: string[]): Map<string, string> {
  const groups = new Map<string, Array<{ path: string; parents: string[] }>>()
  for (const path of paths) {
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
    const name = parts.pop() ?? path
    const group = groups.get(name) ?? []
    group.push({ path, parents: parts })
    groups.set(name, group)
  }
  const labels = new Map<string, string>()
  for (const group of groups.values()) {
    if (group.length < 2) continue
    for (const item of group) {
      let label = '.'
      for (let depth = 1; depth <= item.parents.length; depth++) {
        label = item.parents.slice(-depth).join('/')
        if (!group.some((other) => other !== item && other.parents.slice(-depth).join('/') === label)) break
      }
      labels.set(item.path, label)
    }
  }
  return labels
}
