import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { noteCuaTurnEnded, restoreCuaPreview } from '../../store/cua-preview-store'

export type CuaControlState = {
  used?: boolean
  surface?: { kind: string; app_id?: string } | null
  active: boolean
  available: boolean
  turn_id: string | null
  revision: number
  owner: 'idle' | 'assistant' | 'user'
  transferring?: boolean
  waiting: boolean
  awaiting_permission?: boolean
  paused: boolean
  human_reason: string | null
  unresolved: { call_id: string; turn_id: string } | null
  holder: { owner: string; thread_id: string | null } | null
}

/** A running turn that has not called computer use offers no desktop controls. */
function controllable(value: CuaControlState): CuaControlState {
  return { ...value, active: value.active && value.used !== false }
}

/** Control truth comes from the host, never from the preview's visibility. */
export function CuaControlBar({ threadId, compact = false, onReviewPending }: {
  threadId: string; compact?: boolean
  /** Whether an uncertain outcome still waits for the user's review. */
  onReviewPending?: (pending: boolean) => void
}): React.JSX.Element | null {
  const { t } = useTranslation('common')
  const [state, setState] = useState<CuaControlState | null>(null)
  const [error, setError] = useState('')
  const [fresh, setFresh] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const alive = useRef(true)
  const busy = useRef(false)
  const requestVersion = useRef(0)
  const reportReview = useRef(onReviewPending)
  reportReview.current = onReviewPending
  const path = `/v1/threads/${encodeURIComponent(threadId)}/cua`
  useEffect(() => {
    alive.current = true
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      if (!busy.current) {
        const version = ++requestVersion.current
        try {
          const response = await window.dsGui.runtimeRequest(path, 'GET')
          if (!response.ok) throw new Error(t('cuaControlDisconnected'))
          const value = JSON.parse(response.body) as CuaControlState
          if (!disposed && version === requestVersion.current) {
            setState(controllable(value)); setFresh(true); reportReview.current?.(!!value.unresolved)
            restoreCuaPreview(threadId, { ...value, used: value.used === true })
          }
        } catch {
          if (!disposed && version === requestVersion.current) setFresh(false)
        }
      }
      if (!disposed) timer = setTimeout(() => void poll(), 1000)
    }
    void poll()
    return () => { disposed = true; alive.current = false; clearTimeout(timer) }
  }, [path, t, threadId])

  const transfer = async (owner: 'user' | 'assistant' | 'stopped'): Promise<void> => {
    if (!state?.turn_id || busy.current) return
    busy.current = true; ++requestVersion.current; setPending(owner); setError('')
    try {
      const response = await window.dsGui.runtimeRequest(`${path}/control`, 'POST', JSON.stringify({
        owner, revision: state.revision, turn_id: state.turn_id,
        ...(owner === 'assistant' && state.unresolved ? { reviewed_call_id: state.unresolved.call_id } : {})
      }))
      if (!response.ok) throw new Error(t('cuaControlRetry'))
      const next = JSON.parse(response.body) as CuaControlState
      if (alive.current) {
        setState(controllable(next)); setFresh(true); reportReview.current?.(!!next.unresolved)
        if (owner === 'stopped') noteCuaTurnEnded(threadId, 'stopped')
      }
    } catch (e) {
      if (alive.current) { setError(e instanceof Error ? e.message : String(e)); setFresh(false) }
    } finally {
      busy.current = false
      if (alive.current) setPending(null)
    }
  }

  if (state && !state.active && !state.unresolved) return null
  if (state && !state.available) return <p className="px-3 py-2 text-xs text-ds-muted">{t('cuaControlUnavailable')}</p>
  const status = pending === 'user' || state?.transferring ? 'cuaControlTransferring'
    : pending === 'assistant' ? 'cuaControlResuming'
      : !fresh ? 'cuaControlDisconnected'
        : state?.unresolved ? 'cuaControlUnknown'
          : state?.awaiting_permission ? 'cuaControlPermission'
          : state?.owner === 'user' ? 'cuaControlHuman'
            : state?.waiting ? 'cuaControlWaiting'
              : state?.paused ? 'cuaControlPaused' : state?.active ? 'cuaControlAgent' : 'cuaPreviewEnded'
  const returning = state?.owner === 'user' || (!!state?.paused && !state?.unresolved) || (!state?.active && !!state?.unresolved)
  return <div className="border-t border-ds-border px-3 py-2 text-xs" onPointerDown={event => event.stopPropagation()}>
    {(!compact || status !== 'cuaControlAgent') && <p role="status" className="text-ds-ink">{t(status)}</p>}
    {state?.human_reason && compact ? <p className="mt-1 max-h-24 overflow-y-auto text-ds-ink">{state.human_reason}</p> : state?.human_reason ? <details className="mt-1 text-ds-muted"><summary className="cursor-pointer">{t('cuaControlHelpDetails')}</summary><p className="mt-1 max-h-24 overflow-y-auto">{state.human_reason}</p></details> : null}
    {state?.unresolved ? <p className="mt-1 text-ds-danger">{t('cuaControlUnknownHint')}</p> : null}
    {error ? <p role="alert" className="mt-1 text-ds-danger">{error}</p> : null}
    {state && (state.active || state.unresolved) ? <div className="mt-2 flex items-center gap-2">
      <button type="button" disabled={!fresh || !!pending || !!state.transferring}
        className="rounded-full bg-ds-ink px-3 py-1 text-ds-card disabled:opacity-40"
        onClick={() => void transfer(returning ? 'assistant' : 'user')}>
        {t(state.unresolved && returning ? 'cuaControlReviewed' : returning ? 'cuaControlContinue' : 'cuaControlTakeover')}
      </button>
      <button type="button" hidden={!state.active} disabled={!!pending} className="ml-auto rounded-full border border-ds-border bg-white dark:bg-ds-card px-3 py-1 text-ds-ink hover:bg-ds-hover disabled:opacity-40"
        onClick={() => void transfer('stopped')}>{t('cuaControlStop')}</button>
    </div> : null}
  </div>
}
