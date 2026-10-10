import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  NotebookText,
  ChevronRight,
  Blocks,
  SquareKanban,
  Command,
  MessageCircle,
  PanelLeftClose,
  Plus,
  Search,
  Settings,
  Store
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { formatShortcutLabel, shortcutDefinition } from '@shared/shortcuts'
import { OPEN_SIDEBAR_SEARCH_EVENT, TOGGLE_SESSION_ACTIVITY_EVENT } from '../../lib/shortcuts-runtime'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { ConversationSearchModal } from './ConversationSearchModal'
import { SidebarProjectsColumn } from './SidebarProjectsSection'
import { SidebarPinnedSection } from './SidebarPinnedSection'
import { SidebarChatsSection } from './SidebarChatsSection'
import { SettingsSidebarNav } from '../settings/SettingsSidebarNav'
import { isWorkspaceHidden } from '../../lib/sidebar-chrome'
import { normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { SidebarActivity } from './SidebarActivity'
import { buildSidebarActivity } from '../../lib/sidebar-activity'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import { EmptyHomeLayoutToggle } from './EmptyHomeLayoutToggle'

type Props = {
  threads: NormalizedThread[]
  activeThreadId: string | null
  runtimeReady: boolean
  onSelectThread: (id: string) => void
  onOpenThreadTerminal: (id: string) => Promise<void>
  onDeleteThread: (id: string) => Promise<void>
  onArchiveThread: (id: string) => Promise<void>
  onNewChat: () => void
  /** Workspace (Chats) section "+" — always a temporary chats thread. */
  onNewChatsThread: () => void
  onNewChatInWorkspace: (workspaceRoot: string) => void
  onOpenSettings: (section?: SettingsRouteSection) => void
  onCollapseSidebar: () => void
}

export function Sidebar({
  threads,
  activeThreadId,
  runtimeReady,
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onArchiveThread,
  onNewChat,
  onNewChatsThread,
  onNewChatInWorkspace,
  onOpenSettings,
  onCollapseSidebar
}: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const route = useChatStore((s) => s.route)
  const setRoute = useChatStore((s) => s.setRoute)
  const openMarketplace = useChatStore((s) => s.openMarketplace)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const hideWorkspace = useChatStore((s) => s.hideWorkspace)
  const deleteWorkspace = useChatStore((s) => s.deleteWorkspace)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const togglePin = useChatStore((s) => s.togglePin)
  const [sectionHeaderHost, setSectionHeaderHost] = useState<HTMLDivElement | null>(null)
  const hiddenWorkspacePaths = useChatStore((s) => s.hiddenWorkspacePaths)
  const storedThreads = useChatStore((s) => s.threads)
  const hasVisiblePinned = storedThreads.some((thread) => pinnedThreadIds.includes(thread.id) && !isWorkspaceHidden(normalizeWorkspaceRoot(thread.workspace), hiddenWorkspacePaths))
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const [activityOpen, setActivityOpen] = useState(false)
  const blocks = useChatStore((s) => s.blocks)
  const refreshThreads = useChatStore((s) => s.refreshThreads)
  const { threadIds: taskThreadIds } = useThreadsWithActiveTasks()
  const runningIds = new Set(taskThreadIds)
  for (const [id, watching] of Object.entries(watchTurnCompletion)) {
    if (watching) runningIds.add(id)
  }
  if (busy && activeThreadId) runningIds.add(activeThreadId)
  const activityGroups = buildSidebarActivity({
    threads: storedThreads, hiddenWorkspacePaths, runningIds, unreadThreadIds, activeThreadId,
    activeWaiting: blocks.some((block) =>
      (block.kind === 'approval' || block.kind === 'user_input') && block.status === 'pending')
  })
  const hasActivity = Object.values(activityGroups).some((rows) => rows.length > 0)

  useEffect(() => {
    if (!runtimeReady) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const refresh = async (): Promise<void> => {
      if (document.visibilityState !== 'hidden') await refreshThreads()
      if (!cancelled) timer = setTimeout(() => void refresh(), 5000)
    }
    void refresh()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [runtimeReady, refreshThreads])
  const [toolsExpanded, setToolsExpanded] = useState<boolean | null>(null)
  const settingsActive = route === 'settings'
  const kanbanActive = route === 'kanban'
  const automationActive = route === 'automation'
  const channelsActive = route === 'channels'
  const marketplaceActive = route === 'marketplace'
  const activityShortcutLabel = formatShortcutLabel(shortcutDefinition('toggleSessionActivity').chord)
  const toggleActivity = useCallback(() => {
    setActivityOpen((open) => !open)
    if (settingsActive) setRoute('chat')
  }, [settingsActive, setRoute])

  useEffect(() => {
    window.addEventListener(TOGGLE_SESSION_ACTIVITY_EVENT, toggleActivity)
    return () => window.removeEventListener(TOGGLE_SESSION_ACTIVITY_EVENT, toggleActivity)
  }, [toggleActivity])

  useEffect(() => {
    const onOpenSearch = (): void => {
      setSearchModalOpen(true)
    }
    window.addEventListener(OPEN_SIDEBAR_SEARCH_EVENT, onOpenSearch)
    return () => window.removeEventListener(OPEN_SIDEBAR_SEARCH_EVENT, onOpenSearch)
  }, [])

  return (
    <aside className="ds-drag ds-sidebar-shell ds-frosted relative flex h-full w-full shrink-0 flex-col px-3 pb-3">
      <div className="ds-sidebar-sticky-nav ds-no-drag shrink-0">
        <div className="shrink-0 px-1 pb-2">
          <div className="ds-sidebar-titlebar-row ds-window-drag-region">
            <button
              type="button"
              onClick={onCollapseSidebar}
              className="ds-sidebar-toggle-button ds-no-drag shrink-0"
              aria-label={t('sidebarCollapse')}
              title={t('sidebarCollapse')}
            >
              <PanelLeftClose className="h-4 w-4" strokeWidth={1.85} />
            </button>
            <div className="ds-sidebar-header-actions ds-no-drag">
              <button type="button" className="ds-sidebar-toggle-button"
                aria-label={t('conversationSearchNav')} title={`${t('conversationSearchNav')} (⌘K)`}
                onClick={() => setSearchModalOpen(true)}>
                <Search className="h-4 w-4" strokeWidth={1.8} />
              </button>
              <button type="button" className="ds-sidebar-toggle-button"
                aria-label={t(activityOpen ? 'activityShowProjects' : 'activityShowActivity')}
                title={`${t(activityOpen ? 'activityShowProjects' : 'activityShowActivity')} (${activityShortcutLabel})`}
                aria-pressed={activityOpen} aria-controls="sidebar-activity"
                onClick={toggleActivity}>
                <NotebookText className="h-4 w-4" strokeWidth={1.8} />
                {hasActivity && <span className="ds-activity-indicator" aria-hidden="true" />}
              </button>
            </div>
          </div>
        </div>

        {settingsActive ? null : (
          <nav className="ds-sidebar-top-nav flex flex-col gap-px px-1" aria-label={t('extensions')}>
            <SidebarLink
              icon={<Plus className="h-4 w-4" strokeWidth={2} />}
              label={t('newAgent')}
              onClick={runtimeReady ? onNewChat : undefined}
              disabled={!runtimeReady}
              disabledHint={t('runtimeActionNeedsConnection')}
              shortcut="⌘N"
              variant="action"
            />
            <SidebarLink
              icon={<SquareKanban className="h-4 w-4" strokeWidth={1.75} />}
              label={t('kanbanNav')}
              onClick={() => setRoute('kanban')}
              shortcut="⌘J"
              variant="flat"
              active={kanbanActive}
            />

            <button
              type="button"
              className="ds-sidebar-link ds-sidebar-link--plain ds-no-drag"
              aria-expanded={toolsExpanded ?? (marketplaceActive || automationActive || channelsActive)}
              aria-controls="sidebar-tools"
              onClick={() => setToolsExpanded(!(toolsExpanded ?? (marketplaceActive || automationActive || channelsActive)))}
            >
              <span className="ds-sidebar-link__icon text-ds-muted"><Blocks className="h-4 w-4" strokeWidth={1.75} /></span>
              <span className="min-w-0 flex-1 text-left">{t('sidebarTools')}</span>
              <ChevronRight className={`h-3.5 w-3.5 text-ds-faint ${toolsExpanded ?? (marketplaceActive || automationActive || channelsActive) ? 'rotate-90' : ''}`} />
            </button>
            <div id="sidebar-tools" hidden={!(toolsExpanded ?? (marketplaceActive || automationActive || channelsActive))} className="ml-3 border-l border-ds-border-muted pl-2">
              <SidebarLink
                icon={<Store className="h-4 w-4" strokeWidth={1.9} />}
                label={t('extensions')}
                onClick={() => openMarketplace()}
                variant="flat"
                active={marketplaceActive}
              />

              <SidebarLink
                icon={<CalendarClock className="h-4 w-4" strokeWidth={1.9} />}
                label={t('newAutomationTask')}
                onClick={
                  runtimeReady
                    ? () => {
                        setRoute('automation')
                      }
                    : undefined
                }
                disabled={!runtimeReady}
                disabledHint={t('runtimeActionNeedsConnection')}
                variant="flat"
                active={automationActive}
              />
              <SidebarLink
                icon={<MessageCircle className="h-4 w-4" strokeWidth={1.9} />}
                label={t('messageChannels')}
                onClick={() => setRoute('channels')}
                variant="flat"
                active={channelsActive}
              />
            </div>
          </nav>
        )}
      </div>

      {settingsActive ? (
        <SettingsSidebarNav />
      ) : (
        <>
          <div className="ds-sidebar-middle ds-no-drag min-h-0 flex-1" style={activityOpen ? { display: 'none' } : undefined}>
            <div ref={setSectionHeaderHost} className="ds-sidebar-section-heading ds-no-drag shrink-0" />
            <SidebarProjectsColumn
              headerHost={hasVisiblePinned ? null : sectionHeaderHost}
              threads={threads}
              activeThreadId={activeThreadId}
              runtimeReady={runtimeReady}
              workspaceRoot={workspaceRoot}
              busy={busy}
              watchTurnCompletion={watchTurnCompletion}
              unreadThreadIds={unreadThreadIds}
              pinnedThreadIds={pinnedThreadIds}
              locale={i18n.language}
              pinnedSlot={
                <SidebarPinnedSection
                  headerHost={sectionHeaderHost}
                  onSelectThread={onSelectThread}
                  onOpenThreadTerminal={onOpenThreadTerminal}
                  onDeleteThread={onDeleteThread}
                  onArchiveThread={onArchiveThread}
                  onTogglePin={togglePin}
                  t={t}
                />
              }
              onTogglePin={togglePin}
              onPickWorkspace={() => void chooseWorkspace()}
              onRemoveWorkspace={hideWorkspace}
              onDeleteWorkspace={deleteWorkspace}
              onCreateThreadInWorkspace={onNewChatInWorkspace}
              onSelectThread={onSelectThread}
              onOpenThreadTerminal={onOpenThreadTerminal}
              onDeleteThread={onDeleteThread}
              onArchiveThread={onArchiveThread}
              t={t}
            />

            <div className="ds-sidebar-chats-pane">
              <SidebarChatsSection
                onNewChat={onNewChatsThread}
                onSelectThread={onSelectThread}
                onOpenThreadTerminal={onOpenThreadTerminal}
                onDeleteThread={onDeleteThread}
                onArchiveThread={onArchiveThread}
                onTogglePin={togglePin}
                t={t}
              />
            </div>
          </div>

          {activityOpen && <SidebarActivity groups={activityGroups} activeThreadId={activeThreadId}
            runtimeReady={runtimeReady} onSelectThread={onSelectThread} />}

          <div className="ds-sidebar-footer ds-no-drag flex shrink-0 items-center gap-1 px-1 pt-1">
            <div className="min-w-0 flex-1">
              <SidebarLink
                icon={<Settings className="h-4 w-4" strokeWidth={1.75} />}
                label={t('settings')}
                onClick={() => onOpenSettings('general')}
                variant="footer"
              />
            </div>
            <EmptyHomeLayoutToggle />
          </div>
        </>
      )}

      <ConversationSearchModal
        open={searchModalOpen}
        threads={threads}
        runtimeReady={runtimeReady}
        onClose={() => setSearchModalOpen(false)}
        onSelectThread={onSelectThread}
        onNewChat={onNewChat}
        onAddProject={() => void chooseWorkspace()}
        onOpenKanban={() => setRoute('kanban')}
        onOpenSettings={() => onOpenSettings('general')}
      />
    </aside>
  )
}

type SidebarLinkProps = {
  icon: ReactElement
  label: string
  onClick?: () => void
  disabled?: boolean
  disabledHint?: string
  shortcut?: string
  variant?: 'flat' | 'flat-accent' | 'footer' | 'action'
  active?: boolean
  indent?: boolean
  trailing?: ReactElement
}

function SidebarLink({
  icon,
  label,
  onClick,
  disabled,
  disabledHint,
  shortcut,
  variant = 'flat',
  active = false,
  indent = false,
  trailing
}: SidebarLinkProps): ReactElement {
  const variantClass =
    variant === 'action'
      ? 'ds-sidebar-link--action'
      : variant === 'flat-accent'
        ? 'ds-sidebar-link--accent'
        : variant === 'footer'
          ? 'ds-sidebar-link--footer'
          : 'ds-sidebar-link--plain'
  return (
    <button
      type="button"
      disabled={disabled}
      title={disabled ? disabledHint : undefined}
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`ds-sidebar-link ds-no-drag group ${variantClass} ${active ? 'ds-sidebar-link--active' : ''} ${
        indent ? 'ds-sidebar-link--indent' : ''
      }`}
    >
      <span
        className={`ds-sidebar-link__icon ${
          active
            ? 'text-accent'
            : variant === 'flat-accent'
              ? 'text-accent'
              : variant === 'footer'
                ? 'text-ds-faint'
                : 'text-ds-muted'
        }`}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate text-left">{label}</span>
      {shortcut && !disabled ? (
        <kbd className="ds-kbd ds-sidebar-link-shortcut inline-flex invisible items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono font-medium text-ds-faint group-hover:visible group-focus-within:visible">
          <Command className="h-2.5 w-2.5" strokeWidth={2} />
          {shortcut.replace('⌘', '')}
        </kbd>
      ) : null}
      {trailing ?? null}
    </button>
  )
}
