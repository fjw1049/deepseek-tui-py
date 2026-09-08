import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Copy } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import { deriveQueryTrailItems } from './chat/queryTrail.logic'

export function SessionQueries({ children }: { children: ReactNode }): React.ReactElement {
  const { t } = useTranslation('common')
  const blocks = useChatStore((s) => s.blocks)
  const threadId = useChatStore((s) => s.activeThreadId)
  const scrollToBlock = useChatStore((s) => s.scrollToBlock)
  const queries = useMemo(() => {
    const users = blocks.filter((block) => block.kind === 'user')
    const previews = deriveQueryTrailItems(users)
    return users.map((block, index) => ({
      id: block.id, text: block.text, preview: previews[index]!.preview
    })).reverse()
  }, [blocks])
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxWidth: 420, maxHeight: 360 })
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const jumpTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelJump = (): void => {
    if (jumpTimer.current) clearTimeout(jumpTimer.current)
    jumpTimer.current = null
  }
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelClose = (): void => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = null
  }
  const enter = (event: PointerEvent): void => {
    if (event.pointerType === 'touch' || queries.length === 0) return
    cancelClose()
    setOpen(true)
  }
  const leave = (event: PointerEvent): void => {
    if (event.pointerType === 'touch') return
    cancelClose()
    // Bridge the small gap between the title and its portalled list.
    closeTimer.current = setTimeout(() => setOpen(false), 180)
  }

  useLightDismiss({ open, onDismiss: () => { cancelJump(); setOpen(false) }, refs: [buttonRef, panelRef] })
  useEffect(() => {
    setOpen(false)
    setNotice('')
    setCopiedId(null)
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current)
      if (jumpTimer.current) clearTimeout(jumpTimer.current)
    }
  }, [threadId])
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => { setNotice(''); setCopiedId(null) }, 1600)
    return () => clearTimeout(timer)
  }, [notice, copiedId])
  useLayoutEffect(() => {
    if (!open) return
    const update = (): void => {
      const rect = buttonRef.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.body).zoom) || 1
      const left = rect.left / scale
      const top = rect.bottom / scale + 6
      setPosition({ left, top, width: rect.width / scale,
        maxWidth: Math.max(0, Math.min(420, window.innerWidth / scale - left - 8)),
        maxHeight: Math.max(0, Math.min(360, window.innerHeight / scale - top - 8)) })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(buttonRef.current!)
    window.addEventListener('resize', update)
    return () => { observer.disconnect(); window.removeEventListener('resize', update) }
  }, [open])

  const copy = async (text: string, id: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      setNotice(t('copySuccess'))
    } catch {
      setNotice(t('copyFailed'))
    }
  }

  return <>
    <button
      ref={buttonRef}
      type="button"
      className="ds-no-drag group flex h-7 min-w-0 max-w-[420px] flex-initial select-none items-center gap-2 rounded-full pr-1.5 text-left transition-colors hover:bg-ds-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      disabled={queries.length === 0}
      aria-expanded={open}
      aria-label={t('sessionQueriesHint')}
      title={notice || t('sessionQueriesHint')}
      onPointerEnter={enter}
      onPointerLeave={leave}
      onClick={(event) => {
        cancelClose()
        if (event.detail === 0) setOpen((value) => !value)
        else setOpen(true)
      }}
      onDoubleClick={() => {
        if (queries[0]) void copy(queries[0].text, queries[0].id)
      }}
    >
      <span className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">{children}</span>
      {notice ? <span className="shrink-0 text-[11px] text-ds-muted">{notice}</span> :
        <ChevronDown aria-hidden="true" className={`h-3 w-3 shrink-0 text-ds-faint transition-transform duration-150 motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} />}
    </button>
    <span role="status" className="sr-only">{notice}</span>
    {open && createPortal(
      <div ref={panelRef} onPointerEnter={enter} onPointerLeave={leave} className="ds-no-drag fixed z-[100] overflow-hidden rounded-2xl border border-ds-border bg-[color:var(--ds-card-strong)] p-1 shadow-[0_8px_28px_rgba(0,0,0,0.14)]" style={{ left: position.left, top: position.top, width: 'max-content', minWidth: Math.min(position.width, position.maxWidth), maxWidth: position.maxWidth }}>
        <div className="overflow-y-auto overscroll-contain [scrollbar-width:thin]" style={{ maxHeight: position.maxHeight }}>
          {queries.map((query) => <div
            key={query.id}
            className="group flex h-9 w-full select-none items-center rounded-xl px-2.5 font-ui text-[13px] font-medium leading-6 tracking-[-0.01em] text-ds-ink transition-colors hover:bg-ds-hover focus-within:bg-ds-hover"
          >
            <button
              type="button"
              className="flex h-full min-w-0 flex-1 items-center gap-2.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              title={t('sessionQueryCopyHint')}
              aria-label={`${t('sessionQueryCopyHint')}: ${query.preview}`}
              onClick={(event) => {
                cancelJump()
                if (event.detail > 1) return
                const jump = (): void => {
                  scrollToBlock(query.id)
                  setOpen(false)
                }
                if (event.detail === 0) jump()
                else jumpTimer.current = setTimeout(jump, 400)
              }}
              onDoubleClick={() => {
                cancelJump()
                void copy(query.text, query.id)
              }}
            >
              <span aria-hidden="true" className={`h-1 w-1 shrink-0 rounded-full bg-current ${query === queries[0] ? 'text-ds-muted' : 'text-ds-faint opacity-40'}`} />
              <span className="min-w-0 flex-1 truncate">{query.preview}</span>
            </button>
            <button
              type="button"
              className={`ml-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition-opacity hover:text-ds-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${copiedId === query.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'}`}
              title={t(copiedId === query.id ? 'copySuccess' : 'copyMessage')}
              aria-label={`${t('copyMessage')}: ${query.preview}`}
              onClick={(event) => {
                event.stopPropagation()
                cancelJump()
                void copy(query.text, query.id)
              }}
            >
              {copiedId === query.id ? <Check aria-hidden="true" className="h-3 w-3" /> : <Copy aria-hidden="true" className="h-3 w-3" />}
            </button>
          </div>)}
        </div>
      </div>, document.body
    )}
  </>
}
