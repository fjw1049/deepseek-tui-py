import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ScrollText, MessageSquare, FolderGit2, Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { useLightDismiss } from '../hooks/use-light-dismiss'

type Props = {
  children: ReactNode
  className?: string
}

export function SessionInfoPopover({ children, className = '' }: Props) {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const blocks = useChatStore((s) => s.blocks)
  const chooseWorkspace = useChatStore((s) => s.chooseWorkspace)
  const openSettings = useChatStore((s) => s.openSettings)

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
        <div className="flex flex-col py-0.5">
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
          <div className="my-0.5 border-t border-ds-border/40" />
          <button
            type="button"
            className="flex items-center gap-2 px-3 py-1 text-left text-[14px] text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink"
            onClick={() => { setOpen(false); void chooseWorkspace() }}
          >
            <Settings2 size={14} className="shrink-0 text-ds-faint" />
            <span>{t('sessionInfoEditProject', '编辑项目')}</span>
          </button>
        </div>
      </div>,
      document.body
    )}
  </>
}
