import { useMemo, useRef, useState, type ReactElement } from 'react'
import { History, MessageSquarePlus, Plus, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { formatRelativeTimeCompact } from '../../lib/format-relative-time'
import { normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'
import { SessionHeader } from '../SessionHeader'

const HISTORY_LIMIT = 30

type Props = {
  busy?: boolean
  onNewChat: () => void
  onNewTerminal: () => void
}

/**
 * IDE chat-rail title row — Synara editor-rail pattern:
 * session title · [+] new chat/terminal · [history] project threads.
 */
export function IdeChatRailHeader({ busy = false, onNewChat, onNewTerminal }: Props): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const selectThread = useChatStore((s) => s.selectThread)

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
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, HISTORY_LIMIT)
  }, [threads, workspaceRoot])

  return (
    <div className="ds-ide-chat-rail__header ds-surface-divider flex h-10 shrink-0 items-center gap-1.5 pl-[1.15rem] pr-[0.95rem]">
      <SessionHeader compact className="min-w-0 flex-1" />
      {busy ? (
        <span className="inline-flex shrink-0 rounded-full bg-amber-500/16 px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-950 dark:text-amber-100">
          {t('running')}
        </span>
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
