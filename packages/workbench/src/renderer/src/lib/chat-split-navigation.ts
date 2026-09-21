import { useChatStore } from '../store/chat-store'
import { resolveChatLayoutKey, useChatLayoutStore } from '../store/chat-layout-store'
import { resolveActiveThreadWorkspace } from './workspace-path'

export const CHAT_SPLIT_DRAG_EVENT = 'deepseekgui:chat-split-drag'
export type ChatSplitDrag = { threadId: string; x: number; y: number } | null

export function openThreadInSplit(threadId: string, side: 'left' | 'right' = 'right', paneId?: string): boolean {
  const app = useChatStore.getState()
  const thread = app.threads.find(t => t.id === threadId)
  if (!thread?.workspace || thread.archived) return false
  const layouts = useChatLayoutStore.getState()
  const project = resolveChatLayoutKey(layouts, resolveActiveThreadWorkspace(app.activeThreadId, app.threads, app.workspaceRoot))
  if (paneId) layouts.bind(project, paneId, threadId)
  else if (!layouts.add(project, app.activeThreadId, threadId, side)) return false
  if (app.activeThreadId !== threadId) void app.selectThread(threadId)
  return true
}

export function finishChatSplitDrag(threadId: string, x: number, y: number): boolean {
  const target = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-chat-drop]')
  if (!target) return false
  return openThreadInSplit(threadId, target.dataset.chatDrop === 'left' ? 'left' : 'right', target.dataset.chatDropPane)
}
