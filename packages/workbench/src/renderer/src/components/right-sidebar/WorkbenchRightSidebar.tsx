import type { PointerEvent as ReactPointerEvent, ReactElement, ReactNode } from 'react'
import { lazy, Suspense } from 'react'
import {
  Code2,
  FileEdit,
  Globe2,
  Maximize2,
  Minimize2,
  PanelRight,
  PanelRightClose,
  Terminal
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import type { RightSidebarTab } from '../../lib/right-sidebar-state'
import { AppTerminalPanel } from '../AppTerminalPanel'
import { RightSidebarCollapsedStrip } from './RightSidebarCollapsedStrip'

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
  tab: RightSidebarTab
  width: number
  workspaceRoot: string
  blocks: ChatBlock[]
  devPreviewBlocks: ChatBlock[]
  latestDevPreviewUrl: string | null
  previewError?: string | null
  onPreferredUrlConsumed?: () => void
  onPreviewErrorConsumed?: () => void
  onTabChange: (tab: RightSidebarTab) => void
  onToggleCollapsed: () => void
  onClose: () => void
  onToggleMaximize: () => void
  maximized?: boolean
  onBeginResize: (event: React.PointerEvent<HTMLDivElement>) => void
  onOpenFileInEditor: (path: string) => void
  fillWidth?: boolean
  terminalMountActive?: boolean
}

const TAB_ITEMS: Array<{ id: RightSidebarTab; icon: typeof Code2; labelKey: string }> = [
  { id: 'editor', icon: Code2, labelKey: 'rightSidebarTabEditor' },
  { id: 'changes', icon: FileEdit, labelKey: 'rightSidebarTabChanges' },
  { id: 'terminal', icon: Terminal, labelKey: 'rightSidebarTabTerminal' },
  { id: 'preview', icon: Globe2, labelKey: 'rightSidebarTabPreview' }
]

function TabButton({
  active,
  label,
  icon: Icon,
  onClick
}: {
  active: boolean
  label: string
  icon: typeof Code2
  onClick: () => void
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[12px] font-medium transition ${
        active
          ? 'border-ds-border bg-ds-card text-ds-ink shadow-[0_1px_2px_rgba(0,0,0,0.04)]'
          : 'border-transparent text-ds-faint hover:bg-ds-hover/60 hover:text-ds-muted'
      }`}
      aria-pressed={active}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={1.85} />
      <span className="hidden xl:inline">{label}</span>
    </button>
  )
}

function PanelFallback(): ReactElement {
  return <div className="h-full w-full bg-ds-sidebar" />
}

export function WorkbenchRightSidebar({
  open,
  collapsed,
  tab,
  width,
  workspaceRoot,
  blocks,
  devPreviewBlocks,
  latestDevPreviewUrl,
  previewError = null,
  onPreferredUrlConsumed,
  onPreviewErrorConsumed,
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
  if (tab === 'editor') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <WorkspaceEditorPanel workspaceRoot={workspaceRoot} blocks={blocks} />
      </Suspense>
    )
  } else if (tab === 'changes') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <ChangeInspector
          blocks={blocks}
          className="h-full max-h-full w-full flex-col"
          onOpenFileInEditor={onOpenFileInEditor}
        />
      </Suspense>
    )
  } else if (tab === 'preview') {
    otherPanel = (
      <Suspense fallback={<PanelFallback />}>
        <DevBrowserPanel
          blocks={devPreviewBlocks}
          preferredUrl={latestDevPreviewUrl}
          externalError={previewError}
          onPreferredUrlConsumed={onPreferredUrlConsumed}
          onExternalErrorConsumed={onPreviewErrorConsumed}
          className="h-full max-h-full w-full flex-col"
        />
      </Suspense>
    )
  }

  const terminalVisible = tab === 'terminal'

  return (
    <aside
      className={`ds-workbench-right-panel ds-no-drag relative h-full min-h-0 ${
        fillWidth ? 'min-w-0 w-full flex-1' : 'shrink-0'
      }`}
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
        <div className="ds-no-drag ds-surface-divider flex min-h-[var(--ds-header-height,44px)] shrink-0 items-center gap-1 px-2">
          <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
            {TAB_ITEMS.map((item) => (
              <TabButton
                key={item.id}
                active={tab === item.id}
                label={t(item.labelKey)}
                icon={item.icon}
                onClick={() => onTabChange(item.id)}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={onToggleMaximize}
            className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition hover:bg-ds-hover/70 hover:text-ds-ink ${
              maximized ? 'bg-ds-hover/50 text-ds-ink' : 'text-ds-faint'
            }`}
            aria-label={maximized ? t('rightSidebarRestoreHalf') : t('rightSidebarMaximize')}
            aria-pressed={maximized}
            title={maximized ? t('rightSidebarRestoreHalf') : t('rightSidebarMaximize')}
          >
            {maximized ? (
              <Minimize2 className="h-4 w-4" strokeWidth={1.85} />
            ) : (
              <Maximize2 className="h-4 w-4" strokeWidth={1.85} />
            )}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink"
            aria-label={t('rightSidebarCollapse')}
            title={t('rightSidebarCollapse')}
          >
            <PanelRightClose className="h-4 w-4" strokeWidth={1.85} />
          </button>
        </div>

        <div className="relative min-h-0 flex-1 overflow-hidden">
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
