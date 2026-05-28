/** Minimal TOML section read/write for Workbench config editing (no full parser). */

export function readTomlString(
  content: string,
  key: string,
  options: { section?: string } = {}
): string | null {
  const lines = content.split(/\r?\n/)
  let inSection = !options.section
  for (const line of lines) {
    const sec = line.match(/^\s*\[([^\]]+)\]\s*$/)
    if (sec) {
      inSection = options.section ? sec[1].trim() === options.section : true
      continue
    }
    if (!inSection) continue
    const m = line.match(new RegExp(`^\\s*${key}\\s*=\\s*"([^"]*)"`))
    if (m) return (m[1] ?? '').trim()
    const m2 = line.match(new RegExp(`^\\s*${key}\\s*=\\s*'([^']*)'`))
    if (m2) return (m2[1] ?? '').trim()
  }
  return null
}

export function upsertTomlSections(
  content: string,
  sections: Record<string, Record<string, string | undefined>>
): string {
  const lines = content.split(/\r?\n/)
  const out: string[] = []
  const pending = new Map(Object.entries(sections))

  let currentSection: string | null = null
  const keysWritten = new Set<string>()

  const flushSectionKeys = (sectionName: string): void => {
    const updates = pending.get(sectionName)
    if (!updates) return
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined) continue
      out.push(`${key} = "${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
      keysWritten.add(`${sectionName}::${key}`)
    }
    pending.delete(sectionName)
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    const sec = line.match(/^\s*\[([^\]]+)\]\s*$/)
    if (sec) {
      if (currentSection) flushSectionKeys(currentSection)
      currentSection = sec[1].trim()
      out.push(line)
      continue
    }
    if (currentSection && pending.has(currentSection)) {
      const updates = pending.get(currentSection)!
      let replaced = false
      for (const key of Object.keys(updates)) {
        if (updates[key] === undefined) continue
        const keyRe = new RegExp(`^\\s*${key}\\s*=`)
        if (keyRe.test(line)) {
          out.push(`${key} = "${String(updates[key]).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
          keysWritten.add(`${currentSection}::${key}`)
          delete updates[key]
          replaced = true
          break
        }
      }
      if (replaced) continue
    }
    out.push(line)
  }

  if (currentSection) flushSectionKeys(currentSection)

  for (const [sectionName, updates] of pending) {
    const remaining = Object.entries(updates).filter(([, v]) => v !== undefined)
    if (remaining.length === 0) continue
    if (out.length > 0 && out[out.length - 1].trim() !== '') out.push('')
    out.push(`[${sectionName}]`)
    for (const [key, value] of remaining) {
      out.push(`${key} = "${String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
      keysWritten.add(`${sectionName}::${key}`)
    }
  }

  let result = out.join('\n')
  if (!result.endsWith('\n')) result += '\n'
  return result
}
