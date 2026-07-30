export const LAST_ACTIVE_THREAD_STORAGE_KEY = 'deepseekgui.lastActiveThreadId'

export function readLastActiveThreadId(): string | null {
  try {
    const value = window.localStorage.getItem(LAST_ACTIVE_THREAD_STORAGE_KEY)?.trim()
    return value || null
  } catch {
    return null
  }
}

export function writeLastActiveThreadId(threadId: string | null): void {
  try {
    if (!threadId) {
      window.localStorage.removeItem(LAST_ACTIVE_THREAD_STORAGE_KEY)
      return
    }
    window.localStorage.setItem(LAST_ACTIVE_THREAD_STORAGE_KEY, threadId)
  } catch {
    /* ignore persistence failures */
  }
}
