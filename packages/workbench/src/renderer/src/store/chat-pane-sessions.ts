import { createChatSessionStore, registerChatSessionOwner, useChatStore } from './chat-store'
import type { ChatState } from './chat-store-types'

type Session = ReturnType<typeof createChatSessionStore> & { draft: string; scroll: { top: number; atBottom: boolean }; loading: Promise<void> }
const sessions = new Map<string, Session>()

/** Sessions outlive their panes: closing a view must not interrupt a turn or its queue. */
export function getChatPaneSession(threadId: string, initialDraft = ''): Session {
  const existing = sessions.get(threadId)
  if (existing) return existing
  const session = createChatSessionStore()
  const preferenceKey = `deepseek.chat-pane.${threadId}`
  let saved: { draft?: string; model?: string; mode?: ChatState['composerMode']; effort?: string } = {}
  try { saved = JSON.parse(window.localStorage.getItem(preferenceKey) ?? '{}') ?? {} } catch { /* keep defaults */ }
  let draft = typeof saved.draft === 'string' ? saved.draft : initialDraft
  const persist = (): void => {
    const state = session.store.getState()
    try { window.localStorage.setItem(preferenceKey, JSON.stringify({ draft, model: state.composerModel, mode: state.composerMode, effort: state.composerReasoningEffort })) } catch { /* keep in-memory draft */ }
  }
  const app = useChatStore.getState()
  const thread = app.threads.find(t => t.id === threadId)
  const loadThread = session.store.getState().selectThread
  let afterLoad = (): void => {}
  session.store.setState({
    providerId: app.providerId, runtimeConnection: app.runtimeConnection,
    workspaceRoot: thread?.workspace ?? app.workspaceRoot,
    threads: app.threads, composerPickList: app.composerPickList,
    composerModelMeta: app.composerModelMeta,
    composerModel: typeof saved.model === 'string' ? saved.model : app.activeThreadId === threadId ? app.composerModel : thread?.model ?? app.composerModel,
    composerMode: saved.mode && ['agent', 'plan', 'ask', 'goal'].includes(saved.mode) ? saved.mode : app.composerMode,
    composerReasoningEffort: typeof saved.effort === 'string' ? saved.effort : app.composerReasoningEffort,
    // Navigation belongs to the shared shell, while send/stop/approval stay scoped.
    selectThread: id => id === threadId ? loadThread(id).then(() => afterLoad()) : useChatStore.getState().selectThread(id),
    createThread: options => useChatStore.getState().createThread(options),
    forkThread: (id, throughItemId) => useChatStore.getState().forkThread(id, throughItemId),
    chooseWorkspace: options => useChatStore.getState().chooseWorkspace(options),
    activateWorkspace: (path, options) => useChatStore.getState().activateWorkspace(path, options),
    pinnedThreadIds: app.pinnedThreadIds,
    togglePin: id => useChatStore.getState().togglePin(id),
    deleteThread: id => useChatStore.getState().deleteThread(id),
    archiveThread: id => useChatStore.getState().archiveThread(id),
    openSettings: app.openSettings, setRoute: app.setRoute,
    openMarketplace: app.openMarketplace, openPlugins: app.openPlugins,
    openSkills: app.openSkills, openConnectors: app.openConnectors
  })
  const entry: Session = { ...session, get draft() { return draft }, set draft(value: string) { draft = value; persist() },
    scroll: { top: 0, atBottom: true }, loading: Promise.resolve() }
  const unsubscribe = session.store.subscribe((state, previous) => {
    if (state.composerModel !== previous.composerModel || state.composerMode !== previous.composerMode ||
        state.composerReasoningEffort !== previous.composerReasoningEffort) persist()
    const main = useChatStore.getState()
    if (state.threads !== previous.threads && state.threads !== main.threads) useChatStore.setState({ threads: state.threads })
    if (state.workspaceDirtyTick !== previous.workspaceDirtyTick) useChatStore.setState(s => ({ workspaceDirtyTick: s.workspaceDirtyTick + 1 }))
  })
  let unregisterOwner: (() => void) | undefined
  let disposed = false
  entry.dispose = () => { disposed = true; unregisterOwner?.(); unsubscribe(); session.dispose() }
  sessions.set(threadId, entry)
  afterLoad = () => {
    if (disposed || unregisterOwner || session.store.getState().activeThreadId !== threadId) return
    // The shell and pane share one queue owner when switching between layouts.
    const main = useChatStore.getState()
    if (main.activeThreadId === threadId && main.queuedMessages.length) {
      session.store.setState({ queuedMessages: main.queuedMessages })
    }
    unregisterOwner = registerChatSessionOwner(threadId, session.store)
    if (!session.store.getState().busy && session.store.getState().queuedMessages.length) void session.store.getState().drainQueuedMessages()
  }
  entry.loading = session.store.getState().selectThread(threadId)
  return entry
}

export function syncChatPaneCatalog(state: ChatState): void {
  for (const [threadId, session] of sessions) {
    if (state.runtimeConnection === 'ready' && !state.threads.some(thread => thread.id === threadId && !thread.archived)) {
      session.dispose()
      sessions.delete(threadId)
      continue
    }
    const reconnect = session.store.getState().runtimeConnection !== 'ready' && state.runtimeConnection === 'ready'
    session.store.setState({ threads: state.threads, pinnedThreadIds: state.pinnedThreadIds, runtimeConnection: state.runtimeConnection,
      composerPickList: state.composerPickList, composerModelMeta: state.composerModelMeta })
    if (reconnect && !session.store.getState().activeThreadId) session.loading = session.store.getState().selectThread(threadId)
  }
}

export function disposeChatPaneSessions(): void {
  for (const session of sessions.values()) session.dispose()
  sessions.clear()
}

export function peekChatPaneSession(threadId: string | null): Session | undefined {
  return threadId ? sessions.get(threadId) : undefined
}
