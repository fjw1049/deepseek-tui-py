import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Blocks,
  Cable,
  CalendarClock,
  ChevronRight,
  Command,
  MessageCircle,
  PanelLeftClose,
  Plus,
  Puzzle,
  Settings,
  Sparkles
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { SidebarProjectsSection, SidebarProjectsToolbar } from './SidebarProjectsSection'
import { SidebarPinnedSection } from './SidebarPinnedSection'
import { SidebarChatsSection } from './SidebarChatsSection'

const EXTENSIONS_OPEN_KEY = 'deepseekgui.sidebar.extensionsOpen'

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
  onOpenSettings: (section?: SettingsRouteSection) => void
  onCollapseSidebar: () => void
}

function persistExtensionsOpen(open: boolean): void {
  try {
    window.localStorage.setItem(EXTENSIONS_OPEN_KEY, open ? '1' : '0')
  } catch {
    /* localStorage may be unavailable */
  }
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
  onOpenSettings,
  onCollapseSidebar
}: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const route = useChatStore((s) => s.route)
  const setRoute = useChatStore((s) => s.setRoute)
  const openPlugins = useChatStore((s) => s.openPlugins)
  const openSkills = useChatStore((s) => s.openSkills)
  const openConnectors = useChatStore((s) => s.openConnectors)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const hideWorkspace = useChatStore((s) => s.hideWorkspace)
  const deleteWorkspace = useChatStore((s) => s.deleteWorkspace)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const togglePin = useChatStore((s) => s.togglePin)
  const automationActive = route === 'automation'
  const channelsActive = route === 'channels'
  const pluginsActive = route === 'plugins'
  const skillsActive = route === 'skills'
  const connectorsActive = route === 'connectors'
  const extensionsActive = pluginsActive || skillsActive || connectorsActive
  const [extensionsOpen, setExtensionsOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    if (window.localStorage.getItem(EXTENSIONS_OPEN_KEY) === '1') return true
    return false
  })

  useEffect(() => {
    if (!extensionsActive) return
    setExtensionsOpen(true)
    persistExtensionsOpen(true)
  }, [extensionsActive])

  const toggleExtensions = (): void => {
    setExtensionsOpen((prev) => {
      const next = !prev
      persistExtensionsOpen(next)
      return next
    })
  }

  return (
    <aside className="ds-drag ds-sidebar-shell ds-frosted relative flex h-full w-full shrink-0 flex-col px-3 pb-3">
      <div className="ds-sidebar-sticky-nav ds-no-drag shrink-0">
        <div className="shrink-0 px-1 pb-2">
          <div className="ds-sidebar-titlebar-row">
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

        <nav className="flex flex-col gap-0.5 px-1" aria-label={t('extensions')}>
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
            icon={<Blocks className="h-4 w-4" strokeWidth={1.9} />}
            label={t('extensions')}
            onClick={toggleExtensions}
            variant="flat"
            trailing={
              <ChevronRight
                className={`ds-sidebar-chevron h-3.5 w-3.5 shrink-0 text-ds-faint ${
                  extensionsOpen ? 'ds-sidebar-chevron--open' : ''
                }`}
                strokeWidth={1.9}
              />
            }
          />
          {extensionsOpen ? (
            <div className="ds-sidebar-subgroup flex flex-col gap-0.5">
              <SidebarLink
                icon={<Puzzle className="h-4 w-4" strokeWidth={1.9} />}
                label={t('extPlugins')}
                onClick={() => openPlugins()}
                variant="flat"
                indent
                active={pluginsActive}
              />
              <SidebarLink
                icon={<Sparkles className="h-4 w-4" strokeWidth={1.9} />}
                label={t('extSkills')}
                onClick={() => openSkills()}
                variant="flat"
                indent
                active={skillsActive}
              />
              <SidebarLink
                icon={<Cable className="h-4 w-4" strokeWidth={1.9} />}
                label={t('extConnectors')}
                onClick={() => openConnectors()}
                variant="flat"
                indent
                active={connectorsActive}
              />
            </div>
          ) : null}

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
        </nav>
      </div>

      <SidebarProjectsToolbar
        workspaceRoot={workspaceRoot}
        onPickWorkspace={() => void chooseWorkspace()}
        t={t}
      />

      <div className="ds-sidebar-middle ds-no-drag min-h-0 flex-1">
        <SidebarPinnedSection
          onSelectThread={onSelectThread}
          onOpenThreadTerminal={onOpenThreadTerminal}
          onDeleteThread={onDeleteThread}
          onCompactThread={onCompactThread}
          onTogglePin={togglePin}
          t={t}
        />

        <div className="ds-sidebar-projects-scroll ds-scroll-surface min-h-0 flex-1 overflow-y-auto overscroll-contain">
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
            onRemoveWorkspace={hideWorkspace}
            onDeleteWorkspace={deleteWorkspace}
            onCreateThreadInWorkspace={onNewChatInWorkspace}
            onSelectThread={onSelectThread}
            onOpenThreadTerminal={onOpenThreadTerminal}
            onDeleteThread={onDeleteThread}
            onCompactThread={onCompactThread}
            t={t}
          />
        </div>

        <div className="ds-sidebar-chats-pane">
          <SidebarChatsSection
            onNewChat={onNewChat}
            onSelectThread={onSelectThread}
            onOpenThreadTerminal={onOpenThreadTerminal}
            onDeleteThread={onDeleteThread}
            onCompactThread={onCompactThread}
            onTogglePin={togglePin}
            t={t}
          />
        </div>
      </div>

      <div className="ds-sidebar-footer ds-no-drag shrink-0 px-1 pt-2">
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
        <kbd className="ds-kbd ds-sidebar-link-shortcut hidden items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono font-medium text-ds-faint group-hover:inline-flex group-focus-within:inline-flex">
          <Command className="h-2.5 w-2.5" strokeWidth={2} />
          {shortcut.replace('⌘', '')}
        </kbd>
      ) : null}
      {trailing ?? null}
      {variant === 'footer' ? (
        <ChevronRight className="ds-sidebar-chevron h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} />
      ) : null}
    </button>
  )
}
