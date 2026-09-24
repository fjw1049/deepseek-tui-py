import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChatSplitDragContext, ChatSplitDragHandle } from './ChatSplitDrag'
import { usePaneSwapMotion } from '../../hooks/use-pane-swap-motion'
import { Bookmark, GalleryVerticalEnd, PanelRightDashed, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ChatStoreContext, clearChatSelection, useChatStore } from '../../store/chat-store'
import { CHAT_THREAD_DRAG_MIME, useChatLayoutStore, type ChatLayout } from '../../store/chat-layout-store'
import { getChatPaneSession } from '../../store/chat-pane-sessions'
import { CHAT_SPLIT_DRAG_EVENT, chatSplitDropTarget, finishChatSplitDrag, type ChatSplitDrag } from '../../lib/chat-split-navigation'
import { ChatPaneFocusContext } from './chat-pane-focus'
import { resolveChatSplitPresentation, type ChatSplitPresentation } from '../../lib/chat-split-presentation'
import { ChatSplitTaskPicker } from './ChatSplitTaskPicker'
import { SessionHeader } from '../SessionHeader'
import { SessionInfoPopover } from '../SessionInfoPopover'
import { SessionQueries } from '../SessionQueries'
import { ComposerStage } from './ComposerStage'
import { MessageTimeline } from './MessageTimeline'
import './chat-split.css'

type PaneProps = {
  threadId: string
  onOpenFile: (threadId: string, path: string, line?: number) => void
  onOpenDiff: (threadId: string) => void
}

function ChatPaneHeader(): ReactElement {
  const { t } = useTranslation('common')
  const busy = useChatStore(s => s.busy)
  return <div className="flex min-w-0 items-center gap-2">
    <SessionHeader compact className="ds-chat-split-session" />
    {busy ? <span role="status" aria-label={t('running')} title={t('running')} className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" /> : null}
  </div>
}

function ChatTabTools(): ReactElement {
  const { t } = useTranslation('common')
  const busy = useChatStore(s => s.busy)
  return <>
    <SessionQueries><span className="sr-only">{t('sessionQueriesHint')}</span></SessionQueries>
    {busy ? <span role="status" aria-label={t('running')} className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" /> : null}
  </>
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
          onSend={text => state.sendMessage(text, state.composerMode)}
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
export function ChatSplitWorkspace({ project, layout, getInitialDraft, onFocus, onOpenFile, onOpenDiff, onPresentationChange, renderContext }: {
  project: string; layout: ChatLayout; getInitialDraft: (threadId: string) => string
  onFocus: (threadId: string) => void
  onOpenFile: (threadId: string, path: string, line?: number) => void
  onOpenDiff: (threadId: string) => void
  renderContext?: (threadId: string, onCollapse: () => void) => ReactNode
  onPresentationChange?: (presentation: ChatSplitPresentation) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore(s => s.threads)
  const workspaceRoot = useChatStore(s => s.workspaceRoot)
  const activeThreadId = useChatStore(s => s.activeThreadId)
  const newTaskWorkspace = threads.find(th => th.id === activeThreadId)?.workspace || workspaceRoot || project
  const root = useRef<HTMLDivElement>(null)
  const shell = useRef<HTMLDivElement>(null)
  const tabs = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [contextPane, setContextPane] = useState<string | null>(null)
  const contextTrigger = useRef<HTMLButtonElement | null>(null)
  const contextPanel = useRef<HTMLDivElement>(null)
  useEffect(() => { setContextPane(null) }, [layout.focused])
  useEffect(() => { if (contextPane) contextPanel.current?.focus() }, [contextPane])
  const count = layout.panes.length
  const presentation = resolveChatSplitPresentation(count, layout.arrangement ?? 'grid', size.width, size.height)
  const narrow = presentation === 'tabs'
  const arrangement = narrow ? layout.arrangement ?? 'grid' : presentation
  usePaneSwapMotion(root, { ...layout, arrangement }, narrow)
  useEffect(() => { onPresentationChange?.(presentation) }, [presentation, onPresentationChange])
  useEffect(() => {
    if (narrow) tabs.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [narrow, layout.focused, count])
  const actions = useChatLayoutStore.getState()
  const focus = (id: string, threadId: string | null): void => {
    actions.focus(project, id)
    if (threadId) onFocus(threadId)
  }
  const syncFocus = (): void => {
    const next = useChatLayoutStore.getState().layouts[project]
    const selected = next?.panes.find(p => p.id === next.focused)
    if (selected?.threadId) onFocus(selected.threadId)
    else clearChatSelection(newTaskWorkspace)
  }
  useEffect(() => {
    if (!shell.current) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(shell.current)
    return () => observer.disconnect()
  }, [])
  const resizeHandle = (axis: 'x' | 'y'): ReactElement => <div
    key={axis} role="separator" tabIndex={0} aria-label={t('splitResize')}
    aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'} aria-valuemin={25} aria-valuemax={75}
    aria-valuenow={Math.round(layout[axis] * 100)}
    className={`ds-chat-split-resize ds-chat-split-resize--${axis}`}
    style={axis === 'x' ? { left: `${layout.x * 100}%` } : { top: `${layout.y * 100}%`, left: arrangement === 'grid' && count === 3 ? `${layout.x * 100}%` : 0 }}
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

  const paneActions = (pane: ChatLayout['panes'][number]): ReactElement => <div className="ds-chat-split-pane-actions">
            {pane.threadId && renderContext ? <button type="button" className="ds-chat-split-icon"
              title={t('splitTaskContext')} aria-label={t('splitTaskContext')} aria-expanded={contextPane === pane.id}
              aria-controls={contextPane === pane.id ? `chat-context-${pane.id}` : undefined}
              onClick={event => { contextTrigger.current = event.currentTarget; setContextPane(contextPane === pane.id ? null : pane.id) }}>
              <PanelRightDashed size={15} strokeWidth={1.75} aria-hidden="true" />
            </button> : null}
            {pane.threadId ? <button type="button" className="ds-chat-split-icon" title={t('splitPark')} aria-label={t('splitPark')}
              onClick={() => { actions.park(project, pane.id); syncFocus() }}><GalleryVerticalEnd size={14} aria-hidden="true" /></button> : null}
            {count > 1 ? <button type="button" className="ds-chat-split-icon" title={t('splitClose')} aria-label={t('splitClose')} onClick={() => {
              actions.close(project, pane.id)
              syncFocus()
            }}><X size={14} aria-hidden="true" /></button> : null}
  </div>
  const paneGrip = (pane: ChatLayout['panes'][number], index: number): ReactNode => (
    pane.threadId ? <ChatSplitDragHandle threadId={pane.threadId} onMove={key => {
              const columns = arrangement === 'vertical' ? 1 : arrangement === 'horizontal' ? count : count > 4 ? 3 : 2
              const offset = key === 'ArrowLeft' ? -1 : key === 'ArrowRight' ? 1 : key === 'ArrowUp' ? -columns : columns
              const target = layout.panes[index + offset]
              if (target && pane.threadId) { actions.drop(project, target.id, pane.threadId); onFocus(pane.threadId) }
            }} /> : null
  )
  const focusedPane = layout.panes.find(pane => pane.id === layout.focused)

  return <ChatSplitDragContext><div ref={shell} data-presentation={presentation} className="ds-chat-split-shell min-h-0 min-w-0 flex-1">
    {narrow ? <div className="ds-chat-split-tabbar"><div ref={tabs} className="ds-chat-split-tabs" role="tablist" aria-label={t('splitPanes')}
      title={layout.arrangement === 'tabs' ? undefined : t('splitCompactHint')}>
      {layout.panes.map((pane, index) => <div key={pane.id} className="ds-chat-split-tab-group" data-active={layout.focused === pane.id ? '' : undefined}>
        {layout.focused === pane.id ? paneGrip(pane, index) : null}
        {layout.focused === pane.id && pane.threadId ? <ChatStoreContext.Provider key={`info-${pane.threadId}`} value={getChatPaneSession(pane.threadId, getInitialDraft(pane.threadId)).store}>
          <SessionInfoPopover><Bookmark size={14} strokeWidth={1.75} /></SessionInfoPopover>
        </ChatStoreContext.Provider> : null}
        <button type="button" role="tab" id={`chat-tab-${pane.id}`}
        aria-selected={layout.focused === pane.id} aria-controls={`chat-panel-${pane.id}`} tabIndex={layout.focused === pane.id ? 0 : -1}
        title={threads.find(th => th.id === pane.threadId)?.title ?? t('splitChooseTask')}
        className="ds-chat-split-tab" onClick={() => focus(pane.id, pane.threadId)}
        onKeyDown={event => {
          if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
          event.preventDefault(); event.stopPropagation()
          const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + count) % count
          const next = layout.panes[nextIndex]
          focus(next.id, next.threadId)
          tabs.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]?.focus({ preventScroll: true })
        }}>
        <span className="ds-chat-split-tab-number" aria-hidden="true">{index + 1}</span>
        <span className="ds-chat-split-tab-title">{threads.find(th => th.id === pane.threadId)?.title ?? t('splitChooseTask')}</span>
      </button>
      {layout.focused === pane.id && pane.threadId ? <ChatStoreContext.Provider key={`queries-${pane.threadId}`} value={getChatPaneSession(pane.threadId, getInitialDraft(pane.threadId)).store}>
        <ChatTabTools />
      </ChatStoreContext.Provider> : null}
      {layout.focused === pane.id && !pane.threadId ? <ChatSplitTaskPicker workspace={newTaskWorkspace}
        visibleThreadIds={layout.panes.map(p => p.threadId)}
        onSelect={id => { actions.bind(project, pane.id, id); onFocus(id) }}
        onCreate={async () => { focus(pane.id, null); await useChatStore.getState().createThread({ workspaceRoot: newTaskWorkspace }) }} /> : null}
      </div>)}
    </div>
      {focusedPane ? paneActions(focusedPane) : null}
    </div> : null}
    <div ref={root} className="ds-chat-split-grid" style={{ '--split-x': `${layout.x * 100}%`, '--split-y': `${layout.y * 100}%` } as CSSProperties}>
      {layout.panes.map((pane, index) => {
        const focused = layout.focused === pane.id
        const rowColumns = index < 3 ? 3 : count - 3
        const style: CSSProperties = narrow || count === 1 ? { inset: 0 }
          : arrangement === 'vertical' ? { left: 0, right: 0, top: count === 2 ? (index === 0 ? 0 : 'var(--split-y)') : `${index * 100 / count}%`, bottom: count === 2 ? (index === 0 ? 'calc(100% - var(--split-y))' : 0) : `${(count - index - 1) * 100 / count}%` }
          : arrangement === 'horizontal' && count > 2 ? { top: 0, bottom: 0, left: `${index * 100 / count}%`, right: `${(count - index - 1) * 100 / count}%` } : count === 2
          ? { top: 0, bottom: 0, left: index === 0 ? 0 : 'var(--split-x)', right: index === 0 ? 'calc(100% - var(--split-x))' : 0 }
          : count > 4 ? {
              left: `${(index % 3) * 100 / rowColumns}%`,
              right: `${(rowColumns - index % 3 - 1) * 100 / rowColumns}%`,
              top: index < 3 ? 0 : `${layout.y * 100}%`,
              bottom: index < 3 ? `${(1 - layout.y) * 100}%` : 0 }
          : count === 3 && index === 0 ? { inset: '0 calc(100% - var(--split-x)) 0 0' }
          : { left: count === 3 || index % 2 ? 'var(--split-x)' : 0,
              right: count === 4 && index % 2 === 0 ? 'calc(100% - var(--split-x))' : 0,
              top: (count === 3 ? index === 2 : index >= 2) ? 'var(--split-y)' : 0,
              bottom: (count === 3 ? index === 1 : index < 2) ? 'calc(100% - var(--split-y))' : 0 }
        const session = pane.threadId ? getChatPaneSession(pane.threadId, getInitialDraft(pane.threadId)) : null
        return <section key={pane.id} data-chat-pane={pane.id} data-chat-thread={pane.threadId ?? undefined} data-chat-drop="replace" data-chat-drop-pane={pane.id}
          id={`chat-panel-${pane.id}`} role={narrow ? 'tabpanel' : undefined} aria-labelledby={narrow ? `chat-tab-${pane.id}` : undefined}
          className={`ds-chat-split-pane ${focused ? 'is-focused' : ''}`} aria-label={`${t('splitPane')} ${index + 1}`}
          style={{ ...style, display: narrow && !focused ? 'none' : undefined }}
          onFocusCapture={() => { if (!focused) focus(pane.id, pane.threadId) }}
          onPointerDownCapture={() => { if (!focused) focus(pane.id, pane.threadId) }}>
          {!narrow ? <header className="ds-chat-split-title">
            {paneGrip(pane, index)}
            <div className="min-w-0 flex-1">
              {session ? <ChatStoreContext.Provider value={session.store}>
                <ChatPaneHeader />
              </ChatStoreContext.Provider> : <ChatSplitTaskPicker workspace={newTaskWorkspace}
                visibleThreadIds={layout.panes.map(p => p.threadId)}
                onSelect={id => { actions.bind(project, pane.id, id); onFocus(id) }}
                onCreate={async () => {
                  focus(pane.id, null)
                  await useChatStore.getState().createThread({ workspaceRoot: newTaskWorkspace })
                }} />}

            </div>
            {!narrow ? paneActions(pane) : null}
          </header> : null}
          <div className="ds-chat-split-body">
            {contextPane === pane.id && focused && session && pane.threadId && renderContext ? <div
              ref={contextPanel} id={`chat-context-${pane.id}`} role="region" aria-label={t('splitTaskContext')}
              tabIndex={-1} className="ds-chat-split-context ds-no-drag"
              onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setContextPane(null); contextTrigger.current?.focus() } }}>
              <ChatStoreContext.Provider value={session.store}>
                {renderContext(pane.threadId, () => { setContextPane(null); contextTrigger.current?.focus() })}
              </ChatStoreContext.Provider>
            </div> : null}
            <div className="ds-chat-split-conversation">
            {session && pane.threadId ? <ChatStoreContext.Provider value={session.store}>
              <ChatPaneFocusContext.Provider value={focused}>
                <ChatPaneContent key={pane.threadId} threadId={pane.threadId} onOpenFile={onOpenFile} onOpenDiff={onOpenDiff} />
              </ChatPaneFocusContext.Provider>
            </ChatStoreContext.Provider> : <div className="ds-chat-split-empty">
              <span>{t('splitEmptyHint')}</span>
            </div>}
            </div>
          </div>
        </section>
      })}
      {!narrow && count > 1 && arrangement !== 'vertical' && (arrangement === 'grid' && count <= 4 || count === 2) ? resizeHandle('x') : null}
      {!narrow && (arrangement === 'grid' && count > 2 || arrangement === 'vertical' && count === 2) ? resizeHandle('y') : null}
    </div>
  </div></ChatSplitDragContext>
}

export function ChatSplitDropZone({ children, canAdd }: { children: ReactNode; canAdd: boolean }): ReactElement {
  const { t } = useTranslation('common')
  const root = useRef<HTMLDivElement>(null)
  const ghost = useRef<HTMLDivElement>(null)
  const highlighted = useRef<HTMLElement | null>(null)
  const [drag, setDrag] = useState<{ threadId: string; title: string; hint: string; inside: boolean; canAdd: boolean } | null>(null)
  const [side, setSide] = useState<'left' | 'right' | null>(null)
  useEffect(() => () => { highlighted.current?.removeAttribute('data-drop-hint') }, [])
  const clear = useCallback((): void => {
    highlighted.current?.removeAttribute('data-drop-hint')
    highlighted.current = null
    setDrag(null); setSide(null)
  }, [])
  const update = useCallback((x: number, y: number, threadId: string): void => {
    const app = useChatStore.getState()
    const thread = app.threads.find(item => item.id === threadId && !item.archived && item.workspace)
    if (!thread) { clear(); return }
    const rect = root.current?.getBoundingClientRect()
    if (!rect) return
    const inside = x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
    const panes = [...(root.current?.querySelectorAll<HTMLElement>('[data-chat-pane]') ?? [])]
    const source = panes.find(pane => pane.dataset.chatThread === threadId)
    const allowAdd = canAdd && !source
    const edge = panes.length ? 28 : rect.width * .22
    const position = inside && allowAdd ? x < rect.left + edge ? 'left' : x > rect.right - edge ? 'right' : null : null
    setSide(position)
    const target = inside && !position ? chatSplitDropTarget(x, y)?.closest<HTMLElement>('[data-chat-pane]') ?? null : null
    const hint = position ? t(position === 'left' ? 'splitLeft' : 'splitRight')
      : target && target !== source ? t(source ? 'splitDropSwap' : 'splitDropReplace') : t('splitDragCancel')
    const highlight = target !== source ? target : null
    if (highlighted.current !== highlight) {
      highlighted.current?.removeAttribute('data-drop-hint')
      highlighted.current = highlight
    }
    highlight?.setAttribute('data-drop-hint', hint)
    setDrag(previous => previous?.threadId === threadId && previous.hint === hint && previous.inside === inside && previous.canAdd === allowAdd
      ? previous : { threadId, title: thread.title, hint, inside, canAdd: allowAdd })
    const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
    // Keep the floating label on the pointer without rerendering the conversations on every move.
    root.current?.style.setProperty('--split-drag-x', `${x / scale + 14}px`)
    root.current?.style.setProperty('--split-drag-y', `${y / scale + 14}px`)
    if (ghost.current) ghost.current.style.transform = `translate3d(${x / scale + 14}px, ${y / scale + 14}px, 0)`
  }, [canAdd, clear, t])
  useEffect(() => {
    const onDrag = (event: Event): void => {
      const detail = (event as CustomEvent<ChatSplitDrag>).detail
      if (detail) update(detail.x, detail.y, detail.threadId)
      else clear()
    }
    const onKey = (event: KeyboardEvent): void => { if (event.key === 'Escape') clear() }
    window.addEventListener(CHAT_SPLIT_DRAG_EVENT, onDrag)
    window.addEventListener('dragend', clear)
    window.addEventListener('blur', clear)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener(CHAT_SPLIT_DRAG_EVENT, onDrag); window.removeEventListener('dragend', clear)
      window.removeEventListener('blur', clear); window.removeEventListener('keydown', onKey)
    }
  }, [update, clear])
  return <div ref={root} className="ds-chat-split-dropzone ds-no-drag" onDragOver={event => {
    if (!event.dataTransfer.types.includes(CHAT_THREAD_DRAG_MIME)) return
    event.preventDefault()
  }} onDrop={event => {
    const id = event.dataTransfer.getData(CHAT_THREAD_DRAG_MIME)
    if (!id) return
    event.preventDefault(); finishChatSplitDrag(id, event.clientX, event.clientY); clear()
  }}>
    {children}
    {drag?.inside && drag.canAdd ? (['left', 'right'] as const).map(position => <div key={position}
      data-chat-drop={position} className={`ds-chat-split-drop ds-chat-split-drop--${position} ${side === position ? 'is-active' : ''}`}>
      {t(position === 'left' ? 'splitLeft' : 'splitRight')}
    </div>) : null}
    {drag?.inside && createPortal(<div ref={ghost} className="ds-chat-split-drag-preview" aria-hidden="true"
      style={{ transform: `translate3d(${root.current?.style.getPropertyValue('--split-drag-x') || '0px'}, ${root.current?.style.getPropertyValue('--split-drag-y') || '0px'}, 0)` }}>
      <span className="ds-chat-split-drag-preview__title">{drag.title}</span><span>{drag.hint}</span>
    </div>, document.body)}
  </div>
}
