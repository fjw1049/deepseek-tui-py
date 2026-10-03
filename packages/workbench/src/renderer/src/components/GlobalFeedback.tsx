import { useEffect, useLayoutEffect, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { FeedbackNotice } from './FeedbackNotice'

/** A body-level stack stays above app dialogs and outside transformed/clipped panes. */
export function GlobalFeedbackViewport({ children }: { children: ReactNode }): ReactElement {
  return createPortal(<div id="global-feedback-viewport" className="ds-no-drag pointer-events-none fixed left-1/2 top-14 -translate-x-1/2 z-[10000] flex max-h-[calc(100%-4.25rem)] w-[calc(100%-1.5rem)] max-w-[480px] flex-col gap-2 overflow-y-auto overscroll-contain">{children}</div>, document.body)
}

/** All action feedback shares one stack; standalone dialogs retain a usable fallback. */
export function GlobalFeedback({ children }: { children: ReactNode }): ReactElement {
  const [viewport, setViewport] = useState<HTMLElement | null>(null)
  useLayoutEffect(() => {
    setViewport(document.getElementById('global-feedback-viewport'))
  }, [])
  const content = <div className={viewport
    ? 'ds-no-drag pointer-events-auto min-h-0 shrink-0 rounded-xl shadow-lg'
    : 'ds-no-drag pointer-events-auto fixed left-1/2 top-14 z-[10000] max-h-[calc(100%-4.25rem)] w-[min(480px,calc(100vw-24px))] -translate-x-1/2 overflow-y-auto rounded-xl shadow-lg'}>{children}</div>
  return viewport ? createPortal(content, viewport) : content
}

/** Keep failures until dismissed, replaced, or their originating view is closed. */
export function GlobalErrorNotice({ message, title, actions, occurrence, onDismiss }: { message: string; title?: string; actions?: ReactNode; occurrence?: unknown; onDismiss?: () => void }): ReactElement | null {
  const [dismissedMessage, setDismissedMessage] = useState<string | null>(null)
  useEffect(() => setDismissedMessage(null), [message, occurrence])
  if (dismissedMessage === message) return null
  return <GlobalFeedback><FeedbackNotice tone="error" title={title} actions={actions} message={message} onDismiss={() => {
    setDismissedMessage(message)
    onDismiss?.()
  }} /></GlobalFeedback>
}
