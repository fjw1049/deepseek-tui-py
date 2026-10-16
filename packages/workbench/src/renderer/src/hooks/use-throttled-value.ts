import { useEffect, useState } from 'react'
import { useChatStoreApi } from '../store/chat-store'
import type { ChatState } from '../store/chat-store-types'

/**
 * Read a chat-store value at most once per `intervalMs` without subscribing the
 * calling component to every store write. Streaming text changes every frame;
 * components that only derive something expensive from it (link detection,
 * previews) should sample it instead of re-rendering at frame rate.
 *
 * `select` must be a stable function. A value equal to `resetValue` is applied
 * immediately so derived state is cleared the moment a stream ends.
 */
export function useThrottledChatValue<T>(
  select: (state: ChatState) => T,
  intervalMs: number,
  resetValue?: T
): T {
  const store = useChatStoreApi()
  const [value, setValue] = useState(() => select(store.getState()))

  useEffect(() => {
    let timer: number | null = null
    let lastRun = 0
    const apply = (): void => {
      timer = null
      lastRun = Date.now()
      setValue(select(store.getState()))
    }
    apply()
    const unsubscribe = store.subscribe(() => {
      if (resetValue !== undefined && select(store.getState()) === resetValue) {
        if (timer !== null) window.clearTimeout(timer)
        apply()
        return
      }
      if (timer !== null) return
      timer = window.setTimeout(apply, Math.max(0, intervalMs - (Date.now() - lastRun)))
    })
    return () => {
      unsubscribe()
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [store, select, intervalMs, resetValue])

  return value
}
