export const COMPOSER_INSERT_EVENT = 'deepseekgui:composer-insert'
export const WORKSPACE_PATH_DRAG_MIME = 'application/x-deepseek-workspace-path'

export type ComposerInsertDetail = { text: string }

export function formatComposerPathMention(
  path: string,
  lineStart?: number,
  lineEnd?: number
): string {
  const trimmed = path.trim()
  if (!trimmed) return ''
  const mention = /\s/.test(trimmed) ? `@"${trimmed}"` : `@${trimmed}`
  if (lineStart !== undefined && lineStart >= 1) {
    if (lineEnd !== undefined && lineEnd >= 1 && lineEnd !== lineStart) {
      return `${mention}:${lineStart}-${lineEnd}`
    }
    return `${mention}:${lineStart}`
  }
  return mention
}

export function appendComposerSnippet(current: string, snippet: string): string {
  const piece = snippet.trim()
  if (!piece) return current
  if (!current.trim()) return piece
  if (current.endsWith('\n') || current.endsWith(' ')) return `${current}${piece}`
  return `${current} ${piece}`
}

export function insertComposerSnippet(text: string): void {
  const snippet = text.trim()
  if (!snippet) return
  window.dispatchEvent(
    new CustomEvent<ComposerInsertDetail>(COMPOSER_INSERT_EVENT, { detail: { text: snippet } })
  )
}

export function setWorkspacePathDragData(dataTransfer: DataTransfer, path: string): void {
  const mention = formatComposerPathMention(path)
  dataTransfer.setData(WORKSPACE_PATH_DRAG_MIME, path)
  dataTransfer.setData('text/plain', mention)
  dataTransfer.effectAllowed = 'copy'
}

export function workspacePathFromDrag(dataTransfer: DataTransfer): string {
  return dataTransfer.getData(WORKSPACE_PATH_DRAG_MIME).trim()
}
