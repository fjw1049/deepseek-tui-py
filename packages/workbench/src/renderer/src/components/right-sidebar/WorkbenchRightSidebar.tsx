import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode
} from 'react'
import {
  Check,
  FolderOpen,
  Plus,
  X,
  ListChecks,
  FileEdit,
  Globe2,
  Maximize2,
  Minimize2,
  PanelRight,
  PanelRightClose,
  Terminal
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useRunPanelStore } from '../../store/run-panel-store'
import { useChatStore } from '../../store/chat-store'
import type { ChatBlock } from '../../agent/types'
import type { PreviewElementPick } from '../../lib/preview-element-picker'
import type { ChangeReviewContext } from '../../lib/change-review'
import type { RightSidebarTab } from '../../lib/right-sidebar-state'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { AppTerminalPanel } from '../AppTerminalPanel'
import { RightSidebarCollapsedStrip } from './RightSidebarCollapsedStrip'

const RunPanel = lazy(() => import('./RunPanel').then((module) => ({ default: module.RunPanel })))

const ChangeInspector = lazy(() =>
  import('../ChangeInspector').then((module) => ({ default: module.ChangeInspector }))
)
const DevBrowserPanel = lazy(() =>
  import('../DevBrowserPanel').then((module) => ({ default: module.DevBrowserPanel }))
)
const WorkspaceEditorPanel = lazy(() =>
  import('../workspace-editor/WorkspaceEditorPanel').then((module) => ({
    default: module.WorkspaceEditorPanel
  }))
)

type Props = {
  open: boolean
  collapsed: boolean
  tab: RightSidebarTab | null
  tabs: RightSidebarTab[]
  onCloseTab: (tab: RightSidebarTab) => void
  width: number
  workspaceRoot: string
  blocks: ChatBlock[]
  /** Select this path in Changes when the panel opens from a file_change jump. */
  changesFocusPath?: string | null
  changesContext: ChangeReviewContext
  changesTurnId?: string | null
  changesProjectRoot?: string | null
  onChangesContextChange: (context: ChangeReviewContext) => void
  onChangesFocusPathConsumed?: () => void
  devPreviewBlocks: ChatBlock[]
  latestDevPreviewUrl: string | null
  preferredPreviewFilePath?: string | null
  previewError?: string | null
  onPreferredUrlConsumed?: () => void
  onPreviewErrorConsumed?: () => void
  onPreviewPick?: (pick: PreviewElementPick) => void
  onTabChange: (tab: RightSidebarTab) => void
  onToggleCollapsed: () => void
  onClose: () => void
  onToggleMaximize: () => void
  maximized?: boolean
  onBeginResize: (event: React.PointerEvent<HTMLDivElement>) => void
  onOpenFileInEditor: (path: string, line?: number) => void
  fillWidth?: boolean
  terminalMountActive?: boolean
}

const TAB_ITEMS: Array<{ id: RightSidebarTab; icon: typeof FolderOpen; labelKey: string }> = [
  { id: 'editor', icon: FolderOpen, labelKey: 'rightSidebarTabEditor' },
  { id: 'changes', icon: FileEdit, labelKey: 'rightSidebarTabChanges' },
  { id: 'terminal', icon: Terminal, labelKey: 'rightSidebarTabTerminal' },
  { id: 'preview', icon: Globe2, labelKey: 'rightSidebarTabPreview' },
  { id: 'runs', icon: ListChecks, labelKey: 'rightSidebarTabRuns' }
]

function PanelFallback(): ReactElement {
  return <div className="h-full w-full bg-ds-sidebar" />
}

export function WorkbenchRightSidebar({
  open,
  collapsed,
  tab,
  tabs,
  onCloseTab,
  width,
  workspaceRoot,
  blocks,
  changesFocusPath = null,
  changesContext,
  changesTurnId = null,
  changesProjectRoot = null,
  onChangesContextChange,
  onChangesFocusPathConsumed,
  devPreviewBlocks,
  latestDevPreviewUrl,
  preferredPreviewFilePath = null,
  previewError = null,
  onPreferredUrlConsumed,
  onPreviewErrorConsumed,
  onPreviewPick,
  onTabChange,
  onToggleCollapsed,
  onClose,
  onToggleMaximize,
  maximized = false,
  onBeginResize,
  onOpenFileInEditor,
  fillWidth = false,
  terminalMountActive = true
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const runTarget = useRunPanelStore((state) => state.target)
  const activeThreadId = useChatStore((state) => state.activeThreadId)
  const hasRunSelection = !!runTarget && runTarget.threadId === activeThreadId
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const addButtonRef = useRef<HTMLButtonElement>(null)
  const activeTabRef = useRef<HTMLButtonElement>(null)
  useLightDismiss({ open: menuOpen, onDismiss: () => setMenuOpen(false), refs: [menuRef] })
  useEffect(() => {
    if (!open || collapsed) setMenuOpen(false)
    activeTabRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [open, collapsed, tab])
  useEffect(() => {
    if (menuOpen) menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
  }, [menuOpen])
  const chooseTab = (nextTab: RightSidebarTab): void => {
    onTabChange(nextTab)
    setMenuOpen(false)
    addButtonRef.current?.focus()
  }
  const launcherItems = TAB_ITEMS.filter((item) => item.id !== 'runs' || hasRunSelection)

  if (!open) return null

  if (collapsed) {
    return (
      <aside
        className="ds-workbench-right-panel ds-no-drag relative h-full min-h-0 shrink-0"
        style={{ width: 52 }}
      >
        <RightSidebarCollapsedStrip workspaceRoot={workspaceRoot} onExpand={onToggleCollapsed} />
      </aside>
    )
  }

  let otherPanel: ReactNode = null
  if (tab === 'runs') {
    otherPanel = <Suspense fallback={<PanelFallback />}><RunPanel /></Suspense>
  } else if (tab === 'editor') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <WorkspaceEditorPanel workspaceRoot={workspaceRoot} blocks={blocks} />
      </Suspense>
    )
  } else if (tab === 'changes') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <ChangeInspector
          className="h-full max-h-full w-full flex-col"
          context={changesContext}
          turnId={changesTurnId}
          projectRootOverride={changesProjectRoot}
          onContextChange={onChangesContextChange}
          requestedPath={changesFocusPath}
          onRequestedPathConsumed={onChangesFocusPathConsumed}
          onRevealInEditor={onOpenFileInEditor}
        />
      </Suspense>
    )
  } else if (tab === 'preview') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <DevBrowserPanel
          blocks={devPreviewBlocks}
          preferredUrl={latestDevPreviewUrl}
          preferredFilePath={preferredPreviewFilePath}
          externalError={previewError}
          onPreferredUrlConsumed={onPreferredUrlConsumed}
          onExternalErrorConsumed={onPreviewErrorConsumed}
          onPreviewPick={onPreviewPick}
          className="h-full max-h-full w-full flex-col"
        />
      </Suspense>
    )
  }

  const terminalVisible = tab === 'terminal'
  const visibleTabItems = tabs.flatMap((id) => TAB_ITEMS.filter((item) => item.id === id))

  return (
    <aside
      className={`ds-workbench-right-panel ds-no-drag relative h-full min-h-0 ${
        fillWidth ? 'min-w-0 w-full flex-1' : 'shrink-0'
      }`}
      data-fill-width={fillWidth ? '' : undefined}
      style={fillWidth ? undefined : { width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t('rightPanelResize')}
        className="ds-no-drag group absolute inset-y-0 left-0 z-30 w-2 -translate-x-1/2 cursor-col-resize"
        onPointerDown={onBeginResize}
      >
        {/* Panel's own border-l is the divider; the handle stays invisible. */}
      </div>

      <div className="ds-tool-panel ds-right-panel-surface flex h-full min-h-0 flex-col overflow-hidden bg-ds-sidebar">
        {/* Same height + divider treatment as the workbench topbar so the two
            header lines read as one continuous rule across the card. */}
        <div className="ds-no-drag ds-surface-divider ds-right-panel-tabbar ds-dock-header">
          <div className="ds-dock-tabs" aria-label={t('rightSidebarTitle')}>
            {visibleTabItems.map(({ id, icon: Icon, labelKey }) => (
              <div key={id} className="ds-dock-tab" data-active={tab === id ? '' : undefined}>
                <button
                  ref={tab === id ? activeTabRef : undefined}
                  type="button"
                  aria-pressed={tab === id}
                  onClick={() => onTabChange(id)}
                  className="ds-dock-tab-label"
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="whitespace-nowrap">{t(labelKey)}</span>
                </button>
                <button
                  type="button"
                  aria-label={t('rightSidebarCloseTab', { name: t(labelKey) })}
                  title={t('rightSidebarCloseTab', { name: t(labelKey) })}
                  onClick={() => onCloseTab(id)}
                  className="ds-dock-tab-close"
                ><X className="h-3 w-3" /></button>
              </div>
            ))}
          </div>
          <div ref={menuRef} className="relative shrink-0">
            <button
              ref={addButtonRef}
              type="button"
              aria-label={t('rightSidebarAddPanel')}
              title={t('rightSidebarAddPanel')}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((value) => !value)}
              className="ds-dock-action"
            ><Plus className="h-3.5 w-3.5" /></button>
            {menuOpen ? (
              <div
                role="menu"
                aria-label={t('rightSidebarAddPanel')}
                className="ds-dock-menu"
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    event.stopPropagation()
                    setMenuOpen(false)
                    addButtonRef.current?.focus()
                  } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                    event.preventDefault()
                    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
                    const index = items.indexOf(document.activeElement as HTMLButtonElement)
                    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
                    items[next]?.focus()
                  } else if (event.key === 'Tab') setMenuOpen(false)
                }}
              >
                {launcherItems.map(({ id, icon: Icon, labelKey }) => (
                  <button key={id} type="button" role="menuitem" onClick={() => chooseTab(id)}
                    className="ds-dock-menu-item">
                    <Icon className="h-4 w-4" strokeWidth={1.8} /><span>{t(labelKey)}</span>
                    {tabs.includes(id) ? <Check className="ml-auto h-3.5 w-3.5 text-ds-faint" aria-hidden="true" /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onToggleMaximize}
            className="ds-dock-action"
            aria-label={maximized ? t('rightSidebarRestoreHalf') : t('rightSidebarMaximize')}
            aria-pressed={maximized}
            title={maximized ? t('rightSidebarRestoreHalf') : t('rightSidebarMaximize')}
          >
            {maximized ? (
              <Minimize2 className="h-3.5 w-3.5" strokeWidth={1.85} />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" strokeWidth={1.85} />
            )}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="ds-dock-action"
            aria-label={t('rightSidebarCollapse')}
            title={t('rightSidebarCollapse')}
          >
            <PanelRightClose className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </div>

        <div className="relative min-h-0 flex-1 overflow-hidden">
          {tab === null ? (
            <nav aria-label={t('rightSidebarAddPanel')} className="ds-dock-launcher">
              <div className="ds-dock-launcher-list">
                {launcherItems.map(({ id, icon: Icon, labelKey }) => (
                  <button key={id} type="button" onClick={() => chooseTab(id)}
                    className="ds-dock-launcher-item">
                    <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.8} /><span>{t(labelKey)}</span>
                  </button>
                ))}
              </div>
            </nav>
          ) : null}
          {/* Terminal stays mounted (just hidden) when other tabs are active so
              xterm buffers and the terminal:data IPC listener survive tab
              switches; otherwise switching tabs would unmount the panel and
              drop all session scrollback. */}
          <div className={terminalVisible ? 'h-full w-full' : 'hidden h-full w-full'}>
            <AppTerminalPanel
              workspaceRoot={workspaceRoot}
              mountSurface="sidebar"
              mountActive={terminalMountActive}
              visible={terminalVisible}
              className="h-full max-h-full w-full"
            />
          </div>
          {otherPanel ? (
            <div className="absolute inset-0 h-full w-full">{otherPanel}</div>
          ) : null}
        </div>
      </div>
    </aside>
  )
}

export function RightSidebarToggleButton({
  open,
  onClick,
  className = ''
}: {
  open: boolean
  onClick: () => void
  className?: string
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <button
      type="button"
      onClick={onClick}
      className={`ds-sidebar-toggle-button ds-no-drag shrink-0 ${className}`.trim()}
      aria-label={open ? t('rightSidebarClose') : t('rightSidebarOpen')}
      aria-pressed={open}
      title={open ? t('rightSidebarClose') : t('rightSidebarOpen')}
    >
      {open ? (
        <PanelRightClose className="h-4 w-4" strokeWidth={1.85} />
      ) : (
        <PanelRight className="h-4 w-4" strokeWidth={1.85} />
      )}
    </button>
  )
}
