import type { ChatBlock } from '../agent/types'
import { extractTasksFromBlocks } from '../lib/extract-tasks-from-blocks'
import { useChatStore } from '../store/chat-store'

const blockTaskIdsCache = new WeakMap<ChatBlock[], string[]>()

function blockTaskIds(blocks: ChatBlock[]): string[] {
  let ids = blockTaskIdsCache.get(blocks)
  if (!ids) {
    ids = extractTasksFromBlocks(blocks).map((task) => task.id)
    blockTaskIdsCache.set(blocks, ids)
  }
  return ids
}

/**
 * Whether the active conversation owns one of `activeTaskIds`, read from its
 * loaded blocks (covers tasks created before thread_id attribution). Selects a
 * boolean, so the sidebar does not re-render on every streamed block, and the
 * task scan is shared per blocks array across all subscribers.
 */
export function useActiveThreadHasTask(activeTaskIds: Set<string>): boolean {
  return useChatStore((s) =>
    s.activeThreadId != null && blockTaskIds(s.blocks).some((id) => activeTaskIds.has(id))
  )
}
