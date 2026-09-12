import { useEffect, useRef, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  title: string
  body?: string
  confirmLabel: string
  cancelLabel: string
  /** Destructive confirms (discard changes) render a red confirm button. */
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * In-app replacement for window.confirm at high-stakes editor decisions
 * (closing a dirty tab, discarding edits) so the dialog matches the app chrome.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  destructive = false,
  onConfirm,
  onCancel
}: Props): ReactElement {
  const confirmRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    confirmRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onCancel()
        return
      }
      if (event.key === 'Enter') {
        // A focused button handles Enter itself (native click); don't double-fire.
        const target = event.target as HTMLElement | null
        if (target?.tagName === 'BUTTON') return
        event.preventDefault()
        onConfirm()
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [onCancel, onConfirm])

  if (typeof document === 'undefined') return <></>

  return createPortal(
    <div
      className="ds-no-drag fixed inset-0 z-[140] flex items-center justify-center bg-black/30 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        className="ds-pop w-full max-w-[340px] rounded-xl border border-ds-border bg-ds-elevated p-4 shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
      >
        <div className="text-[13.5px] font-medium text-ds-ink">{title}</div>
        {body ? <div className="mt-1.5 text-[13.5px] leading-5 text-ds-muted">{body}</div> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-8 items-center justify-center rounded-lg border border-ds-border px-3 text-[13.5px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.98]"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            className={`inline-flex h-8 items-center justify-center rounded-lg px-3 text-[13.5px] font-medium text-white transition active:scale-[0.98] ${
              destructive ? 'bg-red-600 hover:bg-red-500' : 'bg-accent hover:bg-accent/85'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
