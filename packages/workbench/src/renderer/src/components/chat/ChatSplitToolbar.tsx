import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Columns2, GalleryVerticalEnd, LayoutGrid, PanelsTopLeft, Plus, Rows2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { MAX_CHAT_PANES, useChatLayoutStore, type ChatArrangement, type ChatLayout } from '../../store/chat-layout-store'
import { ChatStoreContext, clearChatSelection, useChatStore } from '../../store/chat-store'
import { getChatPaneSession } from '../../store/chat-pane-sessions'
import type { ChatSplitPresentation } from '../../lib/chat-split-presentation'

function ParkedPaneStatus() {
  const { t } = useTranslation('common')
  const status = useChatStore(s => s.blocks.some(b =>
    (b.kind === 'approval' || b.kind === 'elevation' || b.kind === 'user_input') && b.status === 'pending')
    ? 'waiting' : s.error ? 'error' : s.busy ? 'running'
      : s.threads.find(thread => thread.id === s.activeThreadId)?.status === 'completed' ? 'completed' : 'idle')
  return <span role="status" className="ds-chat-split-parked-status" data-status={status}>{t(`splitParkedStatus_${status}`)}</span>
}

export function ChatSplitToolbar({ project, layout, onArrange, onAdd, onFocus, presentation }: {
  project: string; layout: ChatLayout; onArrange: (arrangement: ChatArrangement) => void; onAdd: () => void
  onFocus: (threadId: string) => void
  presentation?: ChatSplitPresentation
}) {
  const { t } = useTranslation('common')
  const threads = useChatStore(s => s.threads)
  const workspaceRoot = useChatStore(s => s.workspaceRoot)
  const activeThreadId = useChatStore(s => s.activeThreadId)
  const newTaskWorkspace = threads.find(th => th.id === activeThreadId)?.workspace || workspaceRoot || project
  const parked = layout.parked ?? []
  const arrangementLabel = { tabs: 'splitCompactView', grid: 'splitGrid', horizontal: 'splitHorizontal', vertical: 'splitVertical' }[layout.arrangement ?? 'grid']
  const adaptiveHint = presentation === 'tabs' && layout.arrangement !== 'tabs' ? 'splitCompactHint'
    : layout.panes.length > 1 && presentation === 'grid' && layout.arrangement && layout.arrangement !== 'grid' ? 'splitAutoGridHint' : null
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState<CSSProperties>({})
  const [swapStyle, setSwapStyle] = useState<CSSProperties>({})
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const swapAnchor = useRef<HTMLButtonElement>(null)
  const swapPanel = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const focusOnOpen = useRef(false)
  const panelId = useId()
  const cancelClose = (): void => { if (timer.current) clearTimeout(timer.current) }
  const close = (): void => { cancelClose(); setOpen(false) }
  const leave = (): void => {
    cancelClose()
    timer.current = setTimeout(() => {
      if (!panel.current?.contains(document.activeElement)) setOpen(false)
    }, 180)
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useLightDismiss({ open, refs: [trigger, panel], onDismiss: () => {
    if (panel.current?.contains(document.activeElement)) trigger.current?.focus()
    close()
  } })
  useLightDismiss({ open: !!restoreTarget, refs: [swapAnchor, swapPanel], onDismiss: () => {
    if (swapPanel.current?.contains(document.activeElement)) swapAnchor.current?.focus()
    setRestoreTarget(null)
  } })
  useLayoutEffect(() => {
    if (!open) return
    const update = (): void => {
      const rect = trigger.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
      setStyle({ position: 'fixed', zIndex: 120, top: rect.bottom / scale + 6,
        left: Math.max(8, Math.min(rect.left / scale, window.innerWidth / scale - 208)) })
    }
    update()
    if (focusOnOpen.current) {
      panel.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
      focusOnOpen.current = false
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [open])
  useLayoutEffect(() => {
    if (!restoreTarget) return
    const update = (): void => {
      const rect = swapAnchor.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
      setSwapStyle({ position: 'fixed', zIndex: 120, top: rect.bottom / scale + 6,
        left: Math.max(8, Math.min(rect.left / scale, window.innerWidth / scale - 328)) })
    }
    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => { window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true) }
  }, [restoreTarget])
  useLayoutEffect(() => {
    if (restoreTarget) swapPanel.current?.querySelector<HTMLButtonElement>('button')?.focus()
  }, [restoreTarget])
  const restore = (paneId: string, targetId?: string, anchor?: HTMLButtonElement): void => {
    if (!useChatLayoutStore.getState().restore(project, paneId, targetId)) {
      swapAnchor.current = anchor ?? null
      setRestoreTarget(paneId)
      return
    }
    setRestoreTarget(null)
    const next = useChatLayoutStore.getState().layouts[project]
    const selected = next?.panes.find(p => p.id === next.focused)
    if (selected?.threadId) onFocus(selected.threadId)
    else clearChatSelection(newTaskWorkspace)
  }
  return <div className="ds-chat-split-toolbar ds-no-drag">
    <button ref={trigger} type="button" className="ds-chat-split-task-trigger ds-chat-split-arrangement-trigger" aria-expanded={open}
      title={adaptiveHint ? t(adaptiveHint) : undefined}
      aria-haspopup="dialog" aria-controls={open ? panelId : undefined}
      onMouseEnter={() => { setRestoreTarget(null); cancelClose(); setOpen(true) }} onMouseLeave={leave}
      onClick={() => {
        setRestoreTarget(null)
        cancelClose()
        focusOnOpen.current = !open
        setOpen(true)
        panel.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
      }}>
      <span>{t(arrangementLabel)}</span><ChevronDown size={12} aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={panel} id={panelId} style={style} role="dialog" aria-label={t('splitArrangement')}
      className="ds-project-context-menu ds-chat-split-arrangements ds-no-drag"
      onMouseEnter={cancelClose} onMouseLeave={leave}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== trigger.current) close() }}>
      {([['tabs', PanelsTopLeft, 'splitCompactView'], ['grid', LayoutGrid, 'splitGrid'], ['horizontal', Columns2, 'splitHorizontal'], ['vertical', Rows2, 'splitVertical']] as const).map(([value, Icon, label]) => {
        const selected = (layout.arrangement ?? 'grid') === value
        return <button key={value} type="button"
          className={`ds-project-context-menu__row ${selected ? 'ds-project-context-menu__row--active' : ''}`}
          aria-pressed={selected} onClick={() => { onArrange(value); close(); trigger.current?.focus() }}>
          <Icon size={16} strokeWidth={1.75} aria-hidden="true" /><span className="flex-1">{t(label)}</span>
          {selected ? <Check size={14} aria-hidden="true" /> : null}
        </button>
      })}
    </div>, document.body)}
    <button type="button" className="ds-chat-split-icon" aria-label={t('splitAddPane')}
      title={t(layout.panes.length >= MAX_CHAT_PANES ? 'splitLimit' : 'splitAddPane')}
      disabled={layout.panes.length >= MAX_CHAT_PANES} onClick={onAdd}><Plus size={16} strokeWidth={1.75} aria-hidden="true" /></button>
    {parked.length ? <>
      <span className="ds-chat-split-toolbar-divider" aria-hidden="true" />
      <span className="ds-chat-split-parked-label"><GalleryVerticalEnd size={14} strokeWidth={1.8} aria-hidden="true" />{t('splitParked')}</span>
      <div className="ds-chat-split-parked-list" role="group" aria-label={t('splitParked')}>
        {parked.map(pane => {
          const title = threads.find(th => th.id === pane.threadId)?.title || t('splitChooseTask')
          const session = getChatPaneSession(pane.threadId!)
          return <div key={pane.id} className="ds-chat-split-parked-item">
            <button type="button" className="ds-chat-split-restore" title={title}
              aria-label={t('splitRestoreNamed', { title })} onClick={event => restore(pane.id, undefined, event.currentTarget)}>
              <span className="ds-chat-split-parked-title">{title}</span>
              <ChatStoreContext.Provider value={session.store}><ParkedPaneStatus /></ChatStoreContext.Provider>
            </button>
            <button type="button" className="ds-chat-split-icon" title={t('splitDismissParked')}
              aria-label={t('splitDismissParkedNamed', { title })} onClick={() => {
                useChatLayoutStore.getState().dismissParked(project, pane.id)
                if (restoreTarget === pane.id) setRestoreTarget(null)
              }}>
              <X size={12} aria-hidden="true" />
            </button>
          </div>
        })}
      </div>
      {restoreTarget && parked.some(p => p.id === restoreTarget) && createPortal(
        <div ref={swapPanel} style={swapStyle} role="dialog" aria-label={t('splitRestoreSwap')}
          className="ds-project-context-menu ds-chat-split-swap-menu ds-no-drag">
          <div className="ds-chat-split-restore-targets" role="group" aria-label={t('splitRestoreSwap')}>
            <span>{t('splitRestoreSwap')}</span>
            {layout.panes.map((pane, index) => <button key={pane.id} type="button" className="ds-chat-split-tab"
              onClick={() => restore(restoreTarget, pane.id)}>{index + 1}. {threads.find(th => th.id === pane.threadId)?.title || t('splitChooseTask')}</button>)}
            <button type="button" className="ds-chat-split-tab" onClick={() => { setRestoreTarget(null); swapAnchor.current?.focus() }}>{t('cancel')}</button>
          </div>
        </div>, document.body)}
    </> : null}
  </div>
}
