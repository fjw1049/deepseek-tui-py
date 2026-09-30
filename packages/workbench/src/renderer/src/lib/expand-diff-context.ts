/** Fill a recorded patch's gaps only when its post-edit lines match the file. */
export function expandDiffContext(patch: string, content: string): string | null {
  const source = content.replace(/\r\n/g, '\n').split('\n')
  if (source.at(-1) === '') source.pop()
  const lines = patch.replace(/\r\n/g, '\n').split('\n')
  const firstHunk = lines.findIndex((line) => line.startsWith('@@'))
  if (firstHunk < 0) return null
  const body: string[] = []
  let cursor = 0
  let oldCount = 0
  let newCount = 0
  let expectedOld = 0
  let expectedNew = 0
  let inHunk = false
  for (const line of lines.slice(firstHunk)) {
    if (line.startsWith('@@')) {
      if (inHunk && (oldCount !== expectedOld || newCount !== expectedNew)) return null
      const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/)
      if (!match) return null
      expectedOld = Number(match[2] ?? 1)
      expectedNew = Number(match[4] ?? 1)
      const start = Number(match[3]) - (expectedNew === 0 ? 0 : 1)
      if (start < cursor || start > source.length) return null
      while (cursor < start) body.push(` ${source[cursor++]}`)
      oldCount = 0
      newCount = 0
      inHunk = true
    } else if (line.startsWith('-')) {
      body.push(line)
      oldCount++
    } else if (line.startsWith('+') || line.startsWith(' ')) {
      if (source[cursor] !== line.slice(1)) return null
      body.push(line)
      cursor++
      newCount++
      if (line.startsWith(' ')) oldCount++
    } else if (line && !line.startsWith('\\')) {
      return null
    }
  }
  if (oldCount !== expectedOld || newCount !== expectedNew) return null
  while (cursor < source.length) body.push(` ${source[cursor++]}`)
  const oldLength = body.filter((line) => !line.startsWith('+')).length
  const newLength = source.length
  return [...lines.slice(0, firstHunk), `@@ -${oldLength ? 1 : 0},${oldLength} +${newLength ? 1 : 0},${newLength} @@`, ...body].join('\n')
}
