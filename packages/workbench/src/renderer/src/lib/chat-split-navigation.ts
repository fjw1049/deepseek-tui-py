import i18n from '../i18n'
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
  if (paneId) { if (!layouts.drop(project, paneId, threadId)) return false }
  else if (!layouts.add(project, app.activeThreadId, threadId, side)) return false
  if (app.activeThreadId !== threadId) void app.selectThread(threadId)
  return true
}

export function chatSplitDropTarget(x: number, y: number): HTMLElement | null {
  return document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-chat-drop]') ?? null
}

export function finishChatSplitDrag(threadId: string, x: number, y: number): boolean {
  const target = chatSplitDropTarget(x, y)
  if (!target) return false
  return openThreadInSplit(threadId, target.dataset.chatDrop === 'left' ? 'left' : 'right', target.dataset.chatDropPane)
}


let creatingSplit = false

/** Reserve a pane before selection changes so the current conversation stays in place. */
export async function createConversationInSplit(): Promise<void> {
  const app = useChatStore.getState()
  const active = app.threads.find(thread => thread.id === app.activeThreadId)
  if (creatingSplit || app.route !== 'chat' || app.runtimeConnection !== 'ready' || !active?.workspace || active.archived) return
  const layouts = useChatLayoutStore.getState()
  const project = resolveChatLayoutKey(layouts, active.workspace)
  const previousFocus = layouts.layouts[project]?.focused
  if (!layouts.add(project, active.id)) {
    useChatStore.setState({ error: i18n.t('common:splitLimit') })
    return
  }
  const paneId = useChatLayoutStore.getState().layouts[project].focused
  creatingSplit = true
  try {
    await app.createThread({ workspaceRoot: active.workspace, forceNew: true })
    const created = useChatStore.getState().activeThreadId
    if (created && created !== active.id) {
      useChatLayoutStore.getState().bind(project, paneId, created)
    } else {
      layouts.close(project, paneId)
      if (previousFocus) layouts.focus(project, previousFocus)
    }
  } catch (error) {
    layouts.close(project, paneId)
    if (previousFocus) layouts.focus(project, previousFocus)
    useChatStore.setState({ error: error instanceof Error ? error.message : String(error) })
  } finally {
    creatingSplit = false
  }
}
