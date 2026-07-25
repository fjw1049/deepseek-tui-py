/** Recent conversation-search query strings (local, newest first). */

export const CONVERSATION_SEARCH_HISTORY_KEY = 'deepseekgui.conversationSearchHistory'
export const CONVERSATION_SEARCH_HISTORY_LIMIT = 5

let memoryFallback: string[] = []

function readStorageRaw(): string | null {
  try {
    return window.localStorage.getItem(CONVERSATION_SEARCH_HISTORY_KEY)
  } catch {
    return null
  }
}

function writeStorageRaw(value: string): boolean {
  try {
    window.localStorage.setItem(CONVERSATION_SEARCH_HISTORY_KEY, value)
    return true
  } catch {
    return false
  }
}

export function readConversationSearchHistory(): string[] {
  const raw = readStorageRaw()
  if (raw == null) {
    return [...memoryFallback]
  }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...memoryFallback]
    return parsed
      .filter((item): item is string => typeof item === 'string')
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, CONVERSATION_SEARCH_HISTORY_LIMIT)
  } catch {
    return [...memoryFallback]
  }
}

export function pushConversationSearchHistory(query: string): string[] {
  const trimmed = query.trim()
  if (!trimmed) return readConversationSearchHistory()
  const next = [
    trimmed,
    ...readConversationSearchHistory().filter(
      (item) => item.toLowerCase() !== trimmed.toLowerCase()
    )
  ].slice(0, CONVERSATION_SEARCH_HISTORY_LIMIT)
  memoryFallback = next
  writeStorageRaw(JSON.stringify(next))
  return next
}

/** Test helper — clears memory fallback (and localStorage when available). */
export function clearConversationSearchHistory(): void {
  memoryFallback = []
  try {
    window.localStorage.removeItem(CONVERSATION_SEARCH_HISTORY_KEY)
  } catch {
    /* ignore */
  }
}
