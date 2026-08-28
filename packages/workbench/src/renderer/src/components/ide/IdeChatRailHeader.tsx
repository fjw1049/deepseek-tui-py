import { useCallback, useMemo, useRef, useState, type ReactElement } from 'react'
import {
  History,
  Loader2,
  Maximize2,
  MessageSquarePlus,
  Minimize2,
  Plus,
  SquareSplitHorizontal,
  Terminal,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { formatRelativeTimeCompact } from '../../lib/format-relative-time'
import { normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'
import {
  closeTerminalSessionById,
  createTerminalSessionForWorkspace,
  splitTerminalSessionDown,
  useTerminalSessionStore
} from '../../store/terminal-session-store'
import { SessionHeader } from '../SessionHeader'

const HISTORY_LIMIT = 30

type Props = {
  busy?: boolean
  terminalOpen?: boolean
  terminalMaximized?: boolean
  onNewChat: () => void
  onNewTerminal: () => void
  onCloseTerminal?: () => void
  onToggleMaximize?: () => void
}

/**
 * IDE chat-rail title row — Synara editor-rail pattern:
 * session title · [+] new chat/terminal · [history] project threads.
 */
export function IdeChatRailHeader({
  busy = false,
  terminalOpen = false,
  terminalMaximized = false,
  onNewChat,
  onNewTerminal,
  onCloseTerminal,
  onToggleMaximize
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const selectThread = useChatStore((s) => s.selectThread)
  const sessions = useTerminalSessionStore((s) => s.sessions)
  const activeSessionId = useTerminalSessionStore((s) => s.activeSessionId)
  const splitSessionId = useTerminalSessionStore((s) => s.splitSessionId)
  const creatingSession = useTerminalSessionStore((s) => s.creatingSession)
  const setActiveSessionId = useTerminalSessionStore((s) => s.setActiveSessionId)

  const [newMenuOpen, setNewMenuOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const newMenuRef = useRef<HTMLDivElement | null>(null)
  const historyRef = useRef<HTMLDivElement | null>(null)

  useLightDismiss({
    open: newMenuOpen,
    onDismiss: () => setNewMenuOpen(false),
    refs: [newMenuRef]
  })
  useLightDismiss({
    open: historyOpen,
    onDismiss: () => setHistoryOpen(false),
    refs: [historyRef]
  })

  const projectThreads = useMemo(() => {
    const root = normalizeWorkspaceRoot(workspaceRoot)
    if (!root) return []
    const target = root.toLowerCase()
    return threads
      .filter((thread) => normalizeWorkspaceRoot(thread.workspace).toLowerCase() === target)
      .slice()
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
      .slice(0, HISTORY_LIMIT)
  }, [threads, workspaceRoot])

  const closeTerminalTab = useCallback(
    (sessionId: string) => {
      const remaining = sessions.filter((session) => session.id !== sessionId)
      closeTerminalSessionById(sessionId)
      if (remaining.length === 0) onCloseTerminal?.()
    },
    [onCloseTerminal, sessions]
  )

  return (
    <div className="ds-ide-chat-rail__header ds-surface-divider flex h-10 shrink-0 items-center gap-1.5 pl-[1.15rem] pr-[0.95rem]">
      {terminalOpen ? null : <SessionHeader compact className="min-w-0 flex-1" />}
      {terminalOpen ? (
        <div className="ds-no-drag flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {sessions.map((session, index) => {
            const active = session.id === activeSessionId
            return (
              <span
                key={session.id}
                className={`inline-flex shrink-0 items-center gap-0.5 rounded-md border transition ${
                  active
                    ? 'border-ds-border-muted bg-white/90 text-ds-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.72)] dark:border-white/10 dark:bg-white/10 dark:shadow-none'
                    : 'border-transparent text-ds-faint hover:border-ds-border-muted/60 hover:bg-ds-hover/50 hover:text-ds-ink'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveSessionId(session.id)}
                  className="inline-flex max-w-[160px] items-center gap-1 truncate px-2 py-0.5 text-[12px] font-medium leading-5"
                  title={session.cwd}
                >
                  <Terminal className="h-3 w-3 shrink-0" strokeWidth={1.85} />
                  <span className="truncate">{`${t('terminalPanelTitle')} ${index + 1}`}</span>
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    closeTerminalTab(session.id)
                  }}
                  className="mr-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded text-ds-faint hover:bg-ds-hover/80 hover:text-ds-ink"
                  aria-label={t('terminalCloseTab')}
                  title={t('terminalCloseTab')}
                >
                  <X className="h-2.5 w-2.5" strokeWidth={2} />
                </button>
              </span>
            )
          })}
          <button
            type="button"
            onClick={() => void createTerminalSessionForWorkspace(workspaceRoot)}
            disabled={creatingSession || !workspaceRoot.trim()}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={t('terminalNewTab')}
            title={t('terminalNewTab')}
          >
            {creatingSession ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.9} />
            ) : (
              <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
            )}
          </button>
        </div>
      ) : null}
      {busy ? (
        <span className="inline-flex shrink-0 rounded-full bg-amber-500/16 px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-950 dark:text-amber-100">
          {t('running')}
        </span>
      ) : null}

      {terminalOpen ? (
        <div className="ds-no-drag flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            className={`inline-flex h-7 w-7 items-center justify-center rounded-md transition ${
              splitSessionId
                ? 'bg-ds-hover/70 text-ds-ink'
                : 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            }`}
            title={splitSessionId ? t('terminalUnsplit') : t('terminalSplitDown')}
            aria-label={splitSessionId ? t('terminalUnsplit') : t('terminalSplitDown')}
            aria-pressed={Boolean(splitSessionId)}
            disabled={creatingSession || !workspaceRoot.trim()}
            onClick={() => void splitTerminalSessionDown(workspaceRoot)}
          >
            <SquareSplitHorizontal className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
          <button
            type="button"
            className={`inline-flex h-7 w-7 items-center justify-center rounded-md transition ${
              terminalMaximized
                ? 'bg-ds-hover/70 text-ds-ink'
                : 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            }`}
            title={terminalMaximized ? t('terminalRestore') : t('terminalMaximize')}
            aria-label={terminalMaximized ? t('terminalRestore') : t('terminalMaximize')}
            aria-pressed={terminalMaximized}
            onClick={onToggleMaximize}
          >
            {terminalMaximized ? (
              <Minimize2 className="h-3.5 w-3.5" strokeWidth={1.85} />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" strokeWidth={1.85} />
            )}
          </button>
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
            title={t('terminalCloseTab')}
            aria-label={t('terminalCloseTab')}
            disabled={!activeSessionId}
            onClick={() => {
              if (activeSessionId) closeTerminalTab(activeSessionId)
            }}
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </div>
      ) : null}

      <div className="ds-no-drag flex shrink-0 items-center gap-0.5">
        <div ref={newMenuRef} className="relative">
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
            title={t('ideChatRailNew')}
            aria-label={t('ideChatRailNew')}
            aria-expanded={newMenuOpen}
            aria-haspopup="menu"
            onClick={() => {
              setHistoryOpen(false)
              setNewMenuOpen((open) => !open)
            }}
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
          {newMenuOpen ? (
            <div className="absolute right-0 top-full z-40 mt-1.5 w-44">
              <div className="ds-glass overflow-hidden rounded-xl p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.16)]">
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover/70"
                  onClick={() => {
                    setNewMenuOpen(false)
                    onNewChat()
                  }}
                >
                  <MessageSquarePlus className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.85} />
                  <span>{t('ideChatRailNewChat')}</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover/70"
                  onClick={() => {
                    setNewMenuOpen(false)
                    onNewTerminal()
                  }}
                >
                  <Terminal className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.85} />
                  <span>{t('ideChatRailNewTerminal')}</span>
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div ref={historyRef} className="relative">
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
            title={t('ideChatRailHistory')}
            aria-label={t('ideChatRailHistory')}
            aria-expanded={historyOpen}
            aria-haspopup="menu"
            onClick={() => {
              setNewMenuOpen(false)
              setHistoryOpen((open) => !open)
            }}
          >
            <History className="h-3.5 w-3.5" strokeWidth={1.9} />
          </button>
          {historyOpen ? (
            <div className="absolute right-0 top-full z-40 mt-1.5 w-72">
              <div className="ds-glass max-h-[min(360px,50vh)] overflow-hidden rounded-xl p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.16)]">
                {projectThreads.length === 0 ? (
                  <p className="px-2.5 py-2 text-[12px] text-ds-faint">{t('ideChatRailHistoryEmpty')}</p>
                ) : (
                  <div className="ds-scroll-surface max-h-[min(340px,48vh)] space-y-0.5 overflow-y-auto">
                    {projectThreads.map((thread) => {
                      const active = thread.id === activeThreadId
                      return (
                        <button
                          key={thread.id}
                          type="button"
                          role="menuitem"
                          className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition ${
                            active
                              ? 'bg-accent/[0.1] text-ds-ink'
                              : 'text-ds-ink hover:bg-ds-hover/70'
                          }`}
                          onClick={() => {
                            setHistoryOpen(false)
                            onCloseTerminal?.()
                            if (!active) void selectThread(thread.id)
                          }}
                        >
                          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">
                            {thread.title}
                          </span>
                          <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">
                            {formatRelativeTimeCompact(thread.updatedAt)}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
