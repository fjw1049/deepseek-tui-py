import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ChevronRight,
  Command,
  LayoutGrid,
  Plus,
  Settings,
  Upload
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { WORKBENCH_FEATURES } from '@shared/workbench-features'
import { useChatStore, type SettingsRouteSection } from '../../store/chat-store'
import { SidebarProjectsSection } from './SidebarProjectsSection'

type Props = {
  threads: NormalizedThread[]
  activeThreadId: string | null
  pluginsActive: boolean
  runtimeReady: boolean
  onSelectThread: (id: string) => void
  onDeleteThread: (id: string) => Promise<void>
  onForkThread: (id: string) => Promise<void>
  onResumeThread: (id: string) => Promise<void>
  onCompactThread: (id: string) => Promise<void>
  onExportThread: (id: string) => Promise<{ path: string } | null>
  onNewChat: () => void
  onNewChatInWorkspace: (workspaceRoot: string) => void
  onImportSession: () => void
  onOpenSettings: (section?: SettingsRouteSection) => void
  onOpenPlugins: () => void
}

export function Sidebar({
  threads,
  activeThreadId,
  pluginsActive,
  runtimeReady,
  onSelectThread,
  onDeleteThread,
  onForkThread,
  onResumeThread,
  onCompactThread,
  onExportThread,
  onNewChat,
  onNewChatInWorkspace,
  onImportSession,
  onOpenSettings,
  onOpenPlugins
}: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const deleteWorkspace = useChatStore((s) => s.deleteWorkspace)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)

  return (
    <aside className="ds-drag ds-sidebar-shell ds-frosted relative flex h-full w-full shrink-0 flex-col px-3 pb-3">
      <div className="shrink-0 px-1 pb-2 pt-3">
        <div aria-hidden className="ds-titlebar-safe-block" />
        <div className="flex min-h-8 items-center justify-center px-1 pt-1">
          <div className="ds-sidebar-brand truncate text-center">{t('appName')}</div>
        </div>
        <div className="mx-1 mt-4 border-t border-ds-border-muted/20" />
      </div>

      <div className="ds-no-drag flex flex-col gap-0.5 px-1">
        <SidebarLink
          icon={<Plus className="h-4 w-4" strokeWidth={2} />}
          label={t('newAgent')}
          onClick={runtimeReady ? onNewChat : undefined}
          disabled={!runtimeReady}
          disabledHint={t('runtimeActionNeedsConnection')}
          shortcut="⌘N"
          variant="flat-accent"
        />
        <SidebarLink
          icon={<Upload className="h-4 w-4" strokeWidth={1.85} />}
          label={t('importSession')}
          onClick={runtimeReady ? onImportSession : undefined}
          disabled={!runtimeReady}
          disabledHint={t('runtimeActionNeedsConnection')}
          variant="flat"
        />
        {WORKBENCH_FEATURES.pluginMarketplace ? (
          <SidebarLink
            icon={<LayoutGrid className="h-4 w-4" strokeWidth={1.75} />}
            label={t('plugins')}
            onClick={onOpenPlugins}
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
        locale={i18n.language}
        onPickWorkspace={() => void chooseWorkspace()}
        onRemoveWorkspace={deleteWorkspace}
        onCreateThreadInWorkspace={onNewChatInWorkspace}
        onSelectThread={onSelectThread}
        onDeleteThread={onDeleteThread}
        onForkThread={onForkThread}
        onResumeThread={onResumeThread}
        onCompactThread={onCompactThread}
        onExportThread={onExportThread}
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
      className={`ds-sidebar-link ds-no-drag ${variantClass} ${active ? 'ds-sidebar-link--active' : ''}`}
    >
      <span
        className={`ds-sidebar-link__icon ${
          variant === 'flat-accent'
            ? 'text-accent'
            : variant === 'footer'
              ? 'text-ds-faint'
              : 'text-ds-muted'
        }`}
      >
        {icon}
      </span>
      <span className="flex-1 truncate text-left">{label}</span>
      {shortcut ? (
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
