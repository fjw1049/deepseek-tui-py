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
  // Bare `@@` (no +N) cannot be mapped onto the post-edit file — skip those hunks.
  let hunkMapped = false

  for (const rawLine of patch.split('\n')) {
    if (rawLine.startsWith('@@')) {
      if (hunkMapped) {
        flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
      } else {
        pendingDeletions.length = 0
      }
      const match = rawLine.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (match) {
        newLine = Number.parseInt(match[2]!, 10)
        hunkMapped = Number.isFinite(newLine) && newLine >= 0
      } else {
        hunkMapped = false
        newLine = 0
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

    if (!hunkMapped) {
      continue
    }

    if (rawLine.startsWith('+')) {
      flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
      if (newLine >= 1) addedLines.push(newLine)
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

  if (hunkMapped) {
    flushDeletions(pendingDeletions, Math.max(0, newLine - 1), deletionZones)
  }
  return { addedLines, deletionZones }
}

/** First 1-based line to jump to in the post-edit file (added line, else near a deletion). */
export function firstChangedEditorLine(highlight: EditorDiffHighlight): number | undefined {
  const added = highlight.addedLines.find((line) => line >= 1)
  if (added !== undefined) return added
  const zone = highlight.deletionZones.find((entry) => entry.afterLineNumber >= 1)
  if (!zone) return undefined
  // Deletion-only hunk: land on the line that followed the removed block.
  return zone.afterLineNumber
}

export function firstChangedEditorLineFromPatch(patch: string): number | undefined {
  return firstChangedEditorLine(parseUnifiedDiffForEditor(patch))
}
