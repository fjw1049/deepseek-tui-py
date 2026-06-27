export type EditorDiffDeletionZone = {
  afterLineNumber: number
  text: string
}

export type EditorDiffHighlight = {
  addedLines: number[]
  deletionZones: EditorDiffDeletionZone[]
}

function flushDeletions(
  pending: string[],
  afterLineNumber: number,
  zones: EditorDiffDeletionZone[]
): void {
  if (pending.length === 0) return
  zones.push({
    afterLineNumber: Math.max(0, afterLineNumber),
    text: pending.splice(0, pending.length).join('\n')
  })
}

export function parseUnifiedDiffForEditor(patch: string): EditorDiffHighlight {
  const addedLines: number[] = []
  const deletionZones: EditorDiffDeletionZone[] = []
  const pendingDeletions: string[] = []
  let newLine = 0

  for (const rawLine of patch.split('\n')) {
    if (rawLine.startsWith('@@')) {
      flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
      const match = rawLine.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (match) {
        newLine = Number.parseInt(match[2]!, 10)
      }
      continue
    }

    if (
      /^(\+\+\+|---) /.test(rawLine) ||
      rawLine.startsWith('diff ') ||
      rawLine.startsWith('index ')
    ) {
      continue
    }

    if (rawLine.startsWith('+')) {
      flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
      addedLines.push(newLine)
      newLine += 1
      continue
    }

    if (rawLine.startsWith('-')) {
      pendingDeletions.push(rawLine.slice(1))
      continue
    }

    if (rawLine.startsWith('\\')) {
      continue
    }

    flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
    newLine += 1
  }

  flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
  return { addedLines, deletionZones }
}
