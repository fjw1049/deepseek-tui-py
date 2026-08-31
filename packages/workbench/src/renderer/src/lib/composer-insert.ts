export const COMPOSER_INSERT_EVENT = 'deepseekgui:composer-insert'
export const COMPOSER_RETRY_DRAFT_EVENT = 'deepseekgui:composer-retry-draft'
export const WORKSPACE_PATH_DRAG_MIME = 'application/x-deepseek-workspace-path'

export type ComposerInsertDetail = { text: string }
export type ComposerRetryDraftDetail = { threadId: string }

const pendingRetryDrafts = new Map<string, string[]>()

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

/**
 * Preserve a failed resend draft for the task it belongs to. The composer may
 * currently be showing another task (or be unmounted on Settings), so delivery
 * is pull-based and waits until that task is active with an empty composer.
 */
export function queueComposerRetryDraft(threadId: string, text: string): void {
  const target = threadId.trim()
  const draft = text.trim()
  if (!target || !draft) return
  pendingRetryDrafts.set(target, [...(pendingRetryDrafts.get(target) ?? []), draft])
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent<ComposerRetryDraftDetail>(COMPOSER_RETRY_DRAFT_EVENT, {
        detail: { threadId: target }
      })
    )
  }
}

export function takeComposerRetryDraft(threadId: string): string | null {
  const target = threadId.trim()
  if (!target) return null
  const drafts = pendingRetryDrafts.get(target)
  if (!drafts?.length) return null
  const [next, ...rest] = drafts
  if (rest.length > 0) pendingRetryDrafts.set(target, rest)
  else pendingRetryDrafts.delete(target)
  return next
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
