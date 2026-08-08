/** Minimal TOML section read/write for Workbench config editing (no full parser). */

type TomlScalar = string | number | boolean
type TomlSectionUpdates = Record<string, TomlScalar | undefined>
/** ``null`` removes the key; ``undefined`` leaves it untouched. */
export type TomlTopLevelValue = TomlScalar | readonly string[] | null

function formatTomlScalar(value: TomlScalar): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '0'
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

function formatTomlTopLevelValue(value: Exclude<TomlTopLevelValue, null>): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => formatTomlScalar(String(item))).join(', ')}]`
  }
  return formatTomlScalar(value as TomlScalar)
}

function topLevelRegion(content: string): { head: string; rest: string } {
  const match = content.match(/^\s*\[/m)
  if (!match || match.index === undefined) {
    return { head: content, rest: '' }
  }
  return {
    head: content.slice(0, match.index),
    rest: content.slice(match.index)
  }
}

/** Read a top-level string key (before the first ``[section]``). */
export function readTomlTopLevelString(content: string, key: string): string | null {
  const { head } = topLevelRegion(content)
  const m = head.match(new RegExp(`^\\s*${key}\\s*=\\s*"([^"]*)"`, 'm'))
  if (m) return (m[1] ?? '').trim()
  const m2 = head.match(new RegExp(`^\\s*${key}\\s*=\\s*'([^']*)'`, 'm'))
  return m2 ? (m2[1] ?? '').trim() : null
}

/** Read a top-level string-array key such as ``web_search_providers = ["a", "b"]``. */
export function readTomlTopLevelStringArray(content: string, key: string): string[] | null {
  const { head } = topLevelRegion(content)
  const m = head.match(new RegExp(`^\\s*${key}\\s*=\\s*\\[([^\\]]*)\\]`, 'm'))
  if (!m) return null
  const body = m[1] ?? ''
  const values: string[] = []
  const re = /"([^"]*)"|'([^']*)'/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) {
    values.push((match[1] ?? match[2] ?? '').trim())
  }
  return values
}

/** Upsert or remove top-level keys (never touches ``[section]`` bodies). */
export function upsertTomlTopLevel(
  content: string,
  updates: Record<string, TomlTopLevelValue | undefined>
): string {
  const pending = new Map(
    Object.entries(updates).filter((entry) => entry[1] !== undefined) as Array<
      [string, TomlTopLevelValue]
    >
  )
  if (pending.size === 0) return content.endsWith('\n') ? content : `${content}\n`

  const { head, rest } = topLevelRegion(content)
  const lines = head.length > 0 || content.length === 0 ? head.split(/\r?\n/) : []
  const out: string[] = []

  for (const line of lines) {
    let replaced = false
    for (const [key, value] of pending) {
      const keyRe = new RegExp(`^\\s*${key}\\s*=`)
      if (!keyRe.test(line)) continue
      pending.delete(key)
      if (value === null) {
        replaced = true
        break
      }
      out.push(`${key} = ${formatTomlTopLevelValue(value)}`)
      replaced = true
      break
    }
    if (!replaced) out.push(line)
  }

  for (const [key, value] of pending) {
    if (value === null) continue
    out.push(`${key} = ${formatTomlTopLevelValue(value)}`)
  }

  while (out.length > 0 && out[out.length - 1] === '') out.pop()
  const headText = out.join('\n')
  let result = rest
    ? headText
      ? `${headText}\n${rest}`
      : rest
    : headText
      ? `${headText}\n`
      : ''
  if (!result.endsWith('\n')) result += '\n'
  return result
}

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

/** Read a boolean key from a ``[section]`` (or top-level when section is omitted). */
export function readTomlBool(
  content: string,
  key: string,
  options: { section?: string } = {}
): boolean | null {
  const lines = content.split(/\r?\n/)
  let inSection = !options.section
  for (const line of lines) {
    const sec = line.match(/^\s*\[([^\]]+)\]\s*$/)
    if (sec) {
      inSection = options.section ? sec[1].trim() === options.section : true
      continue
    }
    if (!inSection) continue
    const m = line.match(new RegExp(`^\\s*${key}\\s*=\\s*(true|false)\\s*(?:#.*)?$`, 'i'))
    if (!m) continue
    return m[1]!.toLowerCase() === 'true'
  }
  return null
}

export function upsertTomlSections(
  content: string,
  sections: Record<string, TomlSectionUpdates>
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
      out.push(`${key} = ${formatTomlScalar(value)}`)
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
          const nextValue = updates[key]
          if (nextValue === undefined) continue
          out.push(`${key} = ${formatTomlScalar(nextValue)}`)
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
    const remaining = Object.entries(updates).filter((entry): entry is [string, TomlScalar] => entry[1] !== undefined)
    if (remaining.length === 0) continue
    if (out.length > 0 && out[out.length - 1].trim() !== '') out.push('')
    out.push(`[${sectionName}]`)
    for (const [key, value] of remaining) {
      out.push(`${key} = ${formatTomlScalar(value)}`)
      keysWritten.add(`${sectionName}::${key}`)
    }
  }

  let result = out.join('\n')
  if (!result.endsWith('\n')) result += '\n'
  return result
}
