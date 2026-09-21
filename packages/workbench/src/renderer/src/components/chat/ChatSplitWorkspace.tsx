import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactElement, type ReactNode } from 'react'
import { Folder, PanelsTopLeft, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ChatStoreContext, clearChatSelection, useChatStore } from '../../store/chat-store'
import { CHAT_THREAD_DRAG_MIME, MAX_CHAT_PANES, useChatLayoutStore, type ChatLayout } from '../../store/chat-layout-store'
import { getChatPaneSession } from '../../store/chat-pane-sessions'
import { CHAT_SPLIT_DRAG_EVENT, finishChatSplitDrag, type ChatSplitDrag } from '../../lib/chat-split-navigation'
import { ChatPaneFocusContext } from './chat-pane-focus'
import { ComposerStage } from './ComposerStage'
import { MessageTimeline } from './MessageTimeline'
import './chat-split.css'

type PaneProps = {
  threadId: string
  onOpenFile: (threadId: string, path: string, line?: number) => void
  onOpenDiff: (threadId: string) => void
}

function ChatPaneContent({ threadId, onOpenFile, onOpenDiff }: PaneProps): ReactElement {
  const { t } = useTranslation('common')
  const state = useChatStore(s => s)
  const session = getChatPaneSession(threadId)
  const [input, setInputState] = useState(session.draft)
  const setInput = (value: string): void => { session.draft = value; setInputState(value) }
  const ready = state.activeThreadId === threadId
  return <>
    {state.error ? <div role="alert" className="px-3 py-2 text-sm text-red-500">{state.error}</div> : null}
    {!ready ? <div role="status" className="flex-1 p-4 text-ds-muted">{state.error
      ? <button onClick={() => void state.selectThread(threadId)}>{t('retry')}</button> : t('splitLoading')}</div> : <>
      <MessageTimeline blocks={state.blocks} liveReasoning={state.liveReasoning} live={state.liveAssistant}
        activeThreadId={threadId} runtimeConnection={state.runtimeConnection} stageCentered={false}
        useChatStageWidth={false} forceSimpleEmptyHome scrollMemory={session.scroll}
        onRetryConnection={() => void state.probeRuntime('user')} onOpenSettings={() => state.openSettings('general')}
        onOpenDiagnostics={() => state.openSettings('general')} onSelectSuggestion={setInput}
        onOpenWorkspaceFile={(path, line) => onOpenFile(threadId, path, line)} />
      <div className="ds-chat-split-composer">
        <ComposerStage input={input} setInput={setInput} mode={state.composerMode} setMode={state.setComposerMode}
          busy={state.busy} runtimeReady={state.runtimeConnection === 'ready'} hasActiveThread
          sessionKey={threadId} useChatStageWidth={false} compactChrome
          composerModel={state.composerModel} composerPickList={state.composerPickList}
          onComposerModelChange={state.setComposerModel}
          onSend={text => {
            setInput('')
            void state.sendMessage(text, state.composerMode).then(sent => {
              if (!sent && !session.draft) setInput(text)
            })
          }}
          onInterrupt={() => void state.interrupt()} onCompact={state.compactActiveThread}
          onFork={async () => { await useChatStore.getState().forkThread(threadId) }} onOpenDiff={() => onOpenDiff(threadId)}
          queuedMessages={state.queuedMessages} onRemoveQueuedMessage={state.removeQueuedMessage}
          onWithdrawQueuedMessage={state.withdrawQueuedMessage}
          onSendQueuedMessageNow={id => void state.sendQueuedMessageNow(id)} />
      </div>
    </>}
  </>
}

/** Stable sibling pane hosts keep editors/composers mounted when the grid changes. */
export function ChatSplitWorkspace({ project, layout, getInitialDraft, onFocus, onOpenFile, onOpenDiff }: {
  project: string; layout: ChatLayout; getInitialDraft: (threadId: string) => string
  onFocus: (threadId: string) => void
  onOpenFile: (threadId: string, path: string, line?: number) => void
  onOpenDiff: (threadId: string) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore(s => s.threads)
  const workspaceRoot = useChatStore(s => s.workspaceRoot)
  const activeThreadId = useChatStore(s => s.activeThreadId)
  const newTaskWorkspace = threads.find(th => th.id === activeThreadId)?.workspace || workspaceRoot || project
  const root = useRef<HTMLDivElement>(null)
  const [narrow, setNarrow] = useState(false)
  const count = layout.panes.length
  const actions = useChatLayoutStore.getState()
  const focus = (id: string, threadId: string | null): void => {
    actions.focus(project, id)
    if (threadId) onFocus(threadId)
  }
  useEffect(() => {
    if (!root.current) return
    const observer = new ResizeObserver(([entry]) => setNarrow(entry.contentRect.width < 760))
    observer.observe(root.current)
    return () => observer.disconnect()
  }, [])
  const resizeHandle = (axis: 'x' | 'y'): ReactElement => <div
    key={axis} role="separator" tabIndex={0} aria-label={t('splitResize')}
    aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'} aria-valuemin={25} aria-valuemax={75}
    aria-valuenow={Math.round(layout[axis] * 100)}
    className={`ds-chat-split-resize ds-chat-split-resize--${axis}`}
    style={axis === 'x' ? { left: `${layout.x * 100}%` } : { top: `${layout.y * 100}%`, left: count === 3 ? `${layout.x * 100}%` : 0 }}
    onDoubleClick={() => actions.resize(project, axis, .5)}
    onKeyDown={event => {
      const previous = axis === 'x' ? 'ArrowLeft' : 'ArrowUp'
      const next = axis === 'x' ? 'ArrowRight' : 'ArrowDown'
      if (![previous, next, 'Home'].includes(event.key)) return
      event.preventDefault()
      actions.resize(project, axis, event.key === 'Home' ? .5 : layout[axis] + (event.key === previous ? -.05 : .05))
    }}
    onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId) }}
    onPointerMove={event => {
      if (!event.currentTarget.hasPointerCapture(event.pointerId) || !root.current) return
      const rect = root.current.getBoundingClientRect()
      actions.resize(project, axis, axis === 'x' ? (event.clientX - rect.left) / rect.width : (event.clientY - rect.top) / rect.height)
    }} onPointerUp={event => event.currentTarget.releasePointerCapture(event.pointerId)} />

  return <div className="ds-chat-split-shell min-h-0 min-w-0 flex-1">
    {narrow && count > 1 ? <div className="flex gap-1 overflow-x-auto p-1" role="tablist" aria-label={t('splitPanes')}>
      {layout.panes.map((pane, index) => <button key={pane.id} role="tab" aria-selected={layout.focused === pane.id}
        className="shrink-0 rounded px-2 py-1 text-xs hover:bg-ds-hover" onClick={() => focus(pane.id, pane.threadId)}>
        {index + 1}. {threads.find(th => th.id === pane.threadId)?.title ?? t('splitChooseTask')}
      </button>)}
    </div> : null}
    <div ref={root} className="ds-chat-split-grid" style={{ '--split-x': `${layout.x * 100}%`, '--split-y': `${layout.y * 100}%` } as CSSProperties}>
      {layout.panes.map((pane, index) => {
        const focused = layout.focused === pane.id
        const thread = threads.find(th => th.id === pane.threadId)
        const style: CSSProperties = narrow || count === 1 ? { inset: 0 } : count === 2
          ? { top: 0, bottom: 0, left: index === 0 ? 0 : 'var(--split-x)', right: index === 0 ? 'calc(100% - var(--split-x))' : 0 }
          : count === 3 && index === 0 ? { inset: '0 calc(100% - var(--split-x)) 0 0' }
          : { left: count === 3 || index % 2 ? 'var(--split-x)' : 0,
              right: count === 4 && index % 2 === 0 ? 'calc(100% - var(--split-x))' : 0,
              top: (count === 3 ? index === 2 : index >= 2) ? 'var(--split-y)' : 0,
              bottom: (count === 3 ? index === 1 : index < 2) ? 'calc(100% - var(--split-y))' : 0 }
        const session = pane.threadId ? getChatPaneSession(pane.threadId, getInitialDraft(pane.threadId)) : null
        return <section key={pane.id} data-chat-pane={pane.id} data-chat-drop="replace" data-chat-drop-pane={pane.id}
          className={`ds-chat-split-pane ${focused ? 'is-focused' : ''}`} aria-label={`${t('splitPane')} ${index + 1}`}
          style={{ ...style, display: narrow && !focused ? 'none' : undefined }}
          onFocusCapture={() => { if (!focused) focus(pane.id, pane.threadId) }}
          onPointerDownCapture={() => { if (!focused) focus(pane.id, pane.threadId) }}>
          <header className="ds-chat-split-title">
            <span className="min-w-0 flex-1 truncate cursor-grab" draggable={Boolean(pane.threadId)}
              onDragStart={event => {
                if (!pane.threadId) return
                event.dataTransfer.setData(CHAT_THREAD_DRAG_MIME, pane.threadId)
                event.dataTransfer.effectAllowed = 'move'
              }}>
              <span className="block truncate" title={thread?.title}>{thread?.title ?? t('splitChooseTask')}</span>
              {thread?.workspace ? <span className="ds-chat-split-project" title={thread.workspace}>
                <Folder size={11} aria-hidden="true" /><span className="truncate">{thread.workspace.replace(/\\/g, '/').split('/').filter(Boolean).pop() || thread.workspace}</span>
              </span> : null}
            </span>
            <button type="button" title={t(count >= MAX_CHAT_PANES ? 'splitLimit' : 'splitAdd')} aria-label={t('splitAdd')}
              disabled={count >= MAX_CHAT_PANES} onClick={() => actions.add(project, pane.threadId)}><PanelsTopLeft size={14} aria-hidden="true" /></button>
            {count > 1 ? <button type="button" title={t('splitClose')} aria-label={t('splitClose')} onClick={() => {
              actions.close(project, pane.id)
              const next = useChatLayoutStore.getState().layouts[project]
              const selected = next?.panes.find(p => p.id === next.focused)
              if (selected?.threadId) onFocus(selected.threadId)
              else clearChatSelection(newTaskWorkspace)
            }}><X size={14} aria-hidden="true" /></button> : null}
          </header>
          {session && pane.threadId ? <ChatStoreContext.Provider value={session.store}>
            <ChatPaneFocusContext.Provider value={focused}>
              <ChatPaneContent key={pane.threadId} threadId={pane.threadId} onOpenFile={onOpenFile} onOpenDiff={onOpenDiff} />
            </ChatPaneFocusContext.Provider>
          </ChatStoreContext.Provider> : <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-y-auto p-6 text-sm">
            <p className="text-ds-muted">{t('splitChooseTask')}</p>
            <select aria-label={t('splitChooseTask')} value="" className="max-w-full rounded border border-ds-border bg-ds-elevated p-2"
              onChange={event => { actions.bind(project, pane.id, event.target.value); onFocus(event.target.value) }}>
              <option value="" disabled>{t('splitChooseTask')}</option>
              {threads.filter(th => th.workspace && !th.archived).map(th => <option key={th.id} value={th.id}>{th.workspace?.replace(/\\/g, '/').split('/').filter(Boolean).pop()} · {th.title}</option>)}
            </select>
            <button className="rounded border border-ds-border px-3 py-2 hover:bg-ds-hover" onClick={() => {
              focus(pane.id, null)
              void useChatStore.getState().createThread({ workspaceRoot: newTaskWorkspace })
            }}>{t('splitNewTask')}</button>
          </div>}
        </section>
      })}
      {!narrow && count > 1 ? resizeHandle('x') : null}
      {!narrow && count > 2 ? resizeHandle('y') : null}
    </div>
  </div>
}

export function ChatSplitDropZone({ children, canAdd }: { children: ReactNode; canAdd: boolean }): ReactElement {
  const { t } = useTranslation('common')
  const root = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [side, setSide] = useState<'left' | 'right' | null>(null)
  const clear = useCallback((): void => { setDragging(false); setSide(null) }, [])
  const update = useCallback((x: number, y: number): void => {
    const rect = root.current?.getBoundingClientRect()
    if (!rect || x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) { clear(); return }
    setDragging(true)
    const fraction = (x - rect.left) / rect.width
    setSide(fraction < .22 ? 'left' : fraction > .78 ? 'right' : null)
  }, [clear])
  useEffect(() => {
    const onDrag = (event: Event): void => {
      const detail = (event as CustomEvent<ChatSplitDrag>).detail
      if (detail) update(detail.x, detail.y)
      else clear()
    }
    const onKey = (event: KeyboardEvent): void => { if (event.key === 'Escape') clear() }
    window.addEventListener(CHAT_SPLIT_DRAG_EVENT, onDrag)
    window.addEventListener('dragend', clear)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener(CHAT_SPLIT_DRAG_EVENT, onDrag); window.removeEventListener('dragend', clear); window.removeEventListener('keydown', onKey) }
  }, [update, clear])
  return <div ref={root} className="ds-chat-split-dropzone ds-no-drag" onDragOver={event => {
    if (!event.dataTransfer.types.includes(CHAT_THREAD_DRAG_MIME)) return
    event.preventDefault(); update(event.clientX, event.clientY)
  }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) clear() }}
    onDrop={event => {
      const id = event.dataTransfer.getData(CHAT_THREAD_DRAG_MIME)
      if (!id) return
      event.preventDefault(); finishChatSplitDrag(id, event.clientX, event.clientY); clear()
    }}>
    {children}
    {dragging && canAdd ? (['left', 'right'] as const).map(position => <div key={position}
      data-chat-drop={position} className={`ds-chat-split-drop ds-chat-split-drop--${position} ${side === position ? 'is-active' : ''}`}>
      {t(position === 'left' ? 'splitLeft' : 'splitRight')}
    </div>) : null}
  </div>
}
