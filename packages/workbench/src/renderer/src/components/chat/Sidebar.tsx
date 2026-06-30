import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CalendarClock,
  ChevronRight,
  Command,
  LayoutGrid,
  MessageCircle,
  PanelLeftClose,
  Plus,
  Settings
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { WORKBENCH_FEATURES } from '@shared/workbench-features'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { SidebarProjectsSection } from './SidebarProjectsSection'
import { SidebarChatsSection } from './SidebarChatsSection'

type Props = {
  threads: NormalizedThread[]
  activeThreadId: string | null
  runtimeReady: boolean
  onSelectThread: (id: string) => void
  onOpenThreadTerminal: (id: string) => Promise<void>
  onDeleteThread: (id: string) => Promise<void>
  onCompactThread: (id: string) => Promise<void>
  onNewChat: () => void
  onNewChatInWorkspace: (workspaceRoot: string) => void
  onImportSession: () => void
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
  onCompactThread,
  onNewChat,
  onNewChatInWorkspace,
  onImportSession,
  onOpenSettings,
  onCollapseSidebar
}: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const route = useChatStore((s) => s.route)
  const setRoute = useChatStore((s) => s.setRoute)
  const openPlugins = useChatStore((s) => s.openPlugins)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const deleteWorkspace = useChatStore((s) => s.deleteWorkspace)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const togglePin = useChatStore((s) => s.togglePin)
  const chatActive = route === 'chat'
  const automationActive = route === 'automation'
  const channelsActive = route === 'channels'
  const pluginsActive = route === 'plugins'

  return (
    <aside className="ds-drag ds-sidebar-shell ds-frosted relative flex h-full w-full shrink-0 flex-col px-3 pb-3">
      <div className="shrink-0 px-1 pb-2 pt-3">
        <div aria-hidden className="ds-titlebar-safe-block" />
        <div className="flex min-h-[48px] items-center justify-between px-1 py-1">
          <div className="ds-sidebar-workbench-label">{t('sidebarWorkbench')}</div>
          <button
            type="button"
            onClick={onCollapseSidebar}
            className="ds-sidebar-toggle-button ds-no-drag shrink-0"
            aria-label={t('sidebarCollapse')}
            title={t('sidebarCollapse')}
          >
            <PanelLeftClose className="h-4 w-4" strokeWidth={1.85} />
          </button>
        </div>
      </div>

      <div className="ds-no-drag flex flex-col gap-0.5 px-1">
        <SidebarLink
          icon={<Plus className="h-4 w-4" strokeWidth={2} />}
          label={t('newAgent')}
          onClick={runtimeReady ? onNewChat : undefined}
          disabled={!runtimeReady}
          disabledHint={t('runtimeActionNeedsConnection')}
          shortcut="⌘N"
          variant="flat"
          active={chatActive}
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
        {WORKBENCH_FEATURES.pluginMarketplace ? (
          <SidebarLink
            icon={<LayoutGrid className="h-4 w-4" strokeWidth={1.75} />}
            label={t('plugins')}
            onClick={() => openPlugins()}
            active={pluginsActive}
          />
        ) : null}
      </div>

      <div className="ds-no-drag mx-2 my-3 border-t border-ds-border-muted/15" />

      <SidebarProjectsSection
        threads={threads}
        activeThreadId={activeThreadId}
        runtimeReady={runtimeReady}
        workspaceRoot={workspaceRoot}
        busy={busy}
        watchTurnCompletion={watchTurnCompletion}
        unreadThreadIds={unreadThreadIds}
        pinnedThreadIds={pinnedThreadIds}
        locale={i18n.language}
        onTogglePin={togglePin}
        onPickWorkspace={() => void chooseWorkspace()}
        onRemoveWorkspace={deleteWorkspace}
        onCreateThreadInWorkspace={onNewChatInWorkspace}
        onImportSession={onImportSession}
        onSelectThread={onSelectThread}
        onOpenThreadTerminal={onOpenThreadTerminal}
        onDeleteThread={onDeleteThread}
        onCompactThread={onCompactThread}
        t={t}
      />

      <SidebarChatsSection
        onNewChat={onNewChat}
        onSelectThread={onSelectThread}
        onOpenThreadTerminal={onOpenThreadTerminal}
        onDeleteThread={onDeleteThread}
        onCompactThread={onCompactThread}
        onTogglePin={togglePin}
        t={t}
      />

      <div className="ds-no-drag mt-2 border-t border-ds-border-muted/20 px-1 pt-3">
        <SidebarLink
          icon={<Settings className="h-4 w-4" strokeWidth={1.75} />}
          label={t('settings')}
          onClick={() => onOpenSettings('general')}
          variant="footer"
        />
      </div>
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
  variant?: 'flat' | 'flat-accent' | 'footer'
  active?: boolean
}

function SidebarLink({
  icon,
  label,
  onClick,
  disabled,
  disabledHint,
  shortcut,
  variant = 'flat',
  active = false
}: SidebarLinkProps): ReactElement {
  const variantClass =
    variant === 'flat-accent'
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
      className={`ds-sidebar-link ds-no-drag ${variantClass} ${active ? 'ds-sidebar-link--active' : ''}`}
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
      <span className="flex-1 truncate text-left">{label}</span>
      {shortcut && active ? (
        <kbd className="ds-kbd hidden items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono text-[12px] font-medium text-ds-faint transition-colors duration-200 sm:inline-flex">
          <Command className="h-2.5 w-2.5" strokeWidth={2} />
          {shortcut.replace('⌘', '')}
        </kbd>
      ) : null}
      {variant === 'footer' ? (
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ds-faint transition-colors duration-200" strokeWidth={1.8} />
      ) : null}
    </button>
  )
}
