import type { NormalizedThread } from '../agent/types'

export const CHATS_SORT_MODES = ['recent', 'name_asc', 'created'] as const
export type ChatsSortMode = (typeof CHATS_SORT_MODES)[number]
export const CHATS_SORT_STORAGE_KEY = 'deepseekgui.sidebar.chatsSort'

export function loadChatsSortMode(): ChatsSortMode {
  try {
    const raw = window.localStorage.getItem(CHATS_SORT_STORAGE_KEY)
    if (CHATS_SORT_MODES.some((mode) => mode === raw)) return raw as ChatsSortMode
  } catch {
    /* private window / quota */
  }
  return 'recent'
}

export function persistChatsSortMode(mode: ChatsSortMode): void {
  try {
    window.localStorage.setItem(CHATS_SORT_STORAGE_KEY, mode)
  } catch {
    /* private window / quota */
  }
}

export function sortChats(threads: NormalizedThread[], mode: ChatsSortMode): NormalizedThread[] {
  return [...threads].sort((a, b) => {
    const name = () => a.title.localeCompare(b.title)
    if (mode === 'name_asc') return name()
    const field = mode === 'created' ? 'createdAt' : 'updatedAt'
    return (Date.parse(b[field] ?? '') || 0) - (Date.parse(a[field] ?? '') || 0) || name()
  })
}
