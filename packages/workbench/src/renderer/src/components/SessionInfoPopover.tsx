import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ScrollText, MessageSquare, FolderGit2, Copy, Pin, PinOff, Archive, FolderOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import { revealWorkspacePathInFolder } from '../lib/open-workspace-path'

type Props = {
  children: ReactNode
  className?: string
}

export function SessionInfoPopover({ children, className = '' }: Props) {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const blocks = useChatStore((s) => s.blocks)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const togglePin = useChatStore((s) => s.togglePin)
  const archiveThread = useChatStore((s) => s.archiveThread)

  const thread = useMemo(
    () => (activeThreadId ? threads.find((th) => th.id === activeThreadId) : undefined),
    [activeThreadId, threads]
  )
  const turnCount = useMemo(
    () => blocks.filter((b) => b.kind === 'user').length,
    [blocks]
  )

  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useLightDismiss({ open, onDismiss: () => setOpen(false), refs: [buttonRef, panelRef] })

  useEffect(() => {
    setOpen(false)
  }, [activeThreadId])

  useLayoutEffect(() => {
    if (!open) return
    const update = (): void => {
      const rect = buttonRef.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.body).zoom) || 1
      setPosition({ left: rect.left / scale, top: (rect.bottom / scale) + 6 })
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [open])

  if (!thread) return <>{children}</>

  const projectName = thread.workspace ? thread.workspace.split(/[/\\]/).pop() : undefined
  const pinned = pinnedThreadIds.includes(thread.id)
  const itemClass =
    'flex w-full items-center gap-2.5 rounded-md px-3 py-1 text-left text-[14px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
  const iconClass = 'h-3.5 w-3.5 shrink-0 text-ds-faint'

  return <>
    <button
      ref={buttonRef}
      type="button"
      className={`ds-no-drag flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition-colors hover:bg-ds-hover hover:text-ds-muted ${className}`}
      aria-expanded={open}
      aria-label={t('sessionInfoHint', 'Session info')}
      onClick={() => setOpen((v) => !v)}
    >
      {children}
    </button>
    {open && createPortal(
      <div
        ref={panelRef}
        className="ds-no-drag fixed z-[100] w-[280px] overflow-hidden rounded-xl border border-ds-border bg-[color:var(--ds-card-strong)] shadow-[0_8px_28px_rgba(0,0,0,0.14)]"
        style={{ left: position.left, top: position.top }}
      >
        <div className="flex flex-col py-1">
          {projectName ? (
            <div className="flex items-center gap-2 px-3 py-1">
              <ScrollText size={15} className="shrink-0 text-ds-faint" />
              <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-ds-ink">{projectName}</span>
            </div>
          ) : null}
          {turnCount > 0 ? (
            <div className="flex items-center gap-2 px-3 py-1 text-[14px] text-ds-muted">
              <MessageSquare size={14} className="shrink-0 text-ds-faint" />
              <span>{turnCount} {t('sessionInfoTasks', '个任务')}</span>
            </div>
          ) : null}
          {thread.workspace ? (
            <div className="flex items-center gap-2 px-3 py-1 text-[14px] text-ds-muted">
              <FolderGit2 size={14} className="shrink-0 text-ds-faint" />
              <span className="min-w-0 truncate">{thread.workspace}</span>
            </div>
          ) : null}
          <div className="my-1 h-px bg-ds-border-muted" />
          <button
            type="button"
            className={itemClass}
            disabled={!thread.workspace}
            onClick={() => {
              if (thread.workspace) void navigator.clipboard?.writeText(thread.workspace)
              setOpen(false)
            }}
          >
            <Copy className={iconClass} strokeWidth={1.8} />
            <span className="min-w-0 truncate">{t('threadMenuCopyPath')}</span>
          </button>
          <button
            type="button"
            className={itemClass}
            onClick={() => { togglePin(thread.id); setOpen(false) }}
          >
            {pinned ? <PinOff className={iconClass} strokeWidth={1.8} /> : <Pin className={iconClass} strokeWidth={1.8} />}
            <span className="min-w-0 truncate">{pinned ? t('sidebarUnpinThread') : t('sidebarPinThread')}</span>
          </button>
          <button
            type="button"
            className={itemClass}
            onClick={() => { void archiveThread(thread.id); setOpen(false) }}
          >
            <Archive className={iconClass} strokeWidth={1.8} />
            <span className="min-w-0 truncate">{t('sidebarThreadArchive')}</span>
          </button>
          <button
            type="button"
            className={itemClass}
            disabled={!thread.workspace}
            onClick={() => {
              if (thread.workspace) void revealWorkspacePathInFolder(thread.workspace)
              setOpen(false)
            }}
          >
            <FolderOpen className={iconClass} strokeWidth={1.8} />
            <span className="min-w-0 truncate">{t('threadMenuRevealInFolder')}</span>
          </button>
        </div>
      </div>,
      document.body
    )}
  </>
}
