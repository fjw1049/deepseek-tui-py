import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ConfirmDialog } from '../workspace-editor/ConfirmDialog'
import { Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { noteCuaControl, noteCuaTurnEnded, restoreCuaPreview, useCuaPreviewStore } from '../../store/cua-preview-store'

const ACTIVE_POLL_MS = 1_000
/** Nothing changes between tasks, and the next task's calls ask for a refresh themselves. */
const IDLE_POLL_MS = 3_000
/** One lost request is not a lost connection; the buttons stay usable through it. */
const POLL_FAILURES_BEFORE_DISCONNECTED = 3
const ERROR_VISIBLE_MS = 6_000

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

function heldFor(value: CuaControlState): 'user' | 'paused' | undefined {
  if (!value.active) return undefined
  return value.owner === 'user' ? 'user' : value.paused ? 'paused' : undefined
}

/** The host's own reason for refusing a transfer, when it gave one. */
function refusal(body: string): string | null {
  try {
    const message = (JSON.parse(body) as { detail?: { message?: unknown } }).detail?.message
    return typeof message === 'string' && message ? message : null
  } catch {
    return null
  }
}

/** Control truth comes from the host, never from the preview's visibility. */
export function CuaControlBar({ threadId, compact = false, stopTarget, onReviewPending }: {
  threadId: string; compact?: boolean; stopTarget?: HTMLElement | null
  /** Whether an uncertain outcome still waits for the user's review. */
  onReviewPending?: (pending: boolean) => void
}): React.JSX.Element | null {
  const { t } = useTranslation('common')
  const [state, setState] = useState<CuaControlState | null>(null)
  const [confirmStopTurn, setConfirmStopTurn] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [fresh, setFresh] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const alive = useRef(true)
  const busy = useRef(0)
  const stopping = useRef(false)
  const pollNow = useRef<() => void>(() => undefined)
  const requestVersion = useRef(0)
  const reportReview = useRef(onReviewPending)
  reportReview.current = onReviewPending
  const path = `/v1/threads/${encodeURIComponent(threadId)}/cua`
  useEffect(() => {
    alive.current = true
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    let inFlight = false
    let again = false
    let failures = 0
    let idlePolls = 0
    const poll = async (): Promise<void> => {
      clearTimeout(timer)
      if (inFlight) { again = true; return }
      inFlight = true
      let delay = ACTIVE_POLL_MS
      if (!busy.current) {
        const version = ++requestVersion.current
        try {
          const response = await window.dsGui.runtimeRequest(path, 'GET')
          if (!response.ok) throw new Error(t('cuaControlDisconnected'))
          const value = JSON.parse(response.body) as CuaControlState
          if (!disposed && version === requestVersion.current) {
            failures = 0
            setState(controllable(value)); setFresh(true); reportReview.current?.(!!value.unresolved)
            noteCuaControl(threadId, heldFor(value))
            restoreCuaPreview(threadId, { ...value, used: value.used === true })
            const over = !value.active && !value.unresolved
            if (over) delay = IDLE_POLL_MS
            idlePolls = over ? idlePolls + 1 : 0
            // A completion event lost with the stream must not leave the card live. Twice,
            // because a response can predate the turn that just armed the card.
            if (idlePolls === 2) noteCuaTurnEnded(threadId)
          }
        } catch {
          if (!disposed && version === requestVersion.current &&
              ++failures >= POLL_FAILURES_BEFORE_DISCONNECTED) setFresh(false)
        }
      }
      inFlight = false
      if (!disposed) timer = setTimeout(() => void poll(), again ? 0 : delay)
      again = false
    }
    pollNow.current = () => void poll()
    void poll()
    return () => {
      disposed = true; alive.current = false; clearTimeout(timer)
      pollNow.current = () => undefined
    }
  }, [path, t, threadId])

  // Calls and handoffs change control at once; do not make them wait for the next poll.
  const revision = useCuaPreviewStore(store => store.sessions[threadId]?.revision)
  const ended = useCuaPreviewStore(store => store.sessions[threadId]?.phase === 'ended')
  const seenRevision = useRef(revision)
  useEffect(() => {
    if (seenRevision.current === revision) return
    seenRevision.current = revision
    pollNow.current()
  }, [revision])

  useEffect(() => {
    if (!error) return
    const timer = setTimeout(() => setError(''), ERROR_VISIBLE_MS)
    return () => clearTimeout(timer)
  }, [error])

  const transfer = async (owner: 'user' | 'assistant' | 'stopped'): Promise<void> => {
    // Stop never waits: it is what ends a transfer that is taking too long.
    if (!state?.turn_id || (busy.current && owner !== 'stopped') || stopping.current) return
    stopping.current = owner === 'stopped'
    busy.current += 1; ++requestVersion.current; setPending(owner); setError('')
    try {
      const response = await window.dsGui.runtimeRequest(`${path}/control`, 'POST', JSON.stringify({
        owner, revision: state.revision, turn_id: state.turn_id,
        ...(owner === 'assistant' && state.unresolved ? { reviewed_call_id: state.unresolved.call_id } : {})
      }))
      if (!response.ok) throw new Error(refusal(response.body) ?? t('cuaControlRetry'))
      const next = JSON.parse(response.body) as CuaControlState
      if (alive.current) {
        setState(controllable(next)); setFresh(true); reportReview.current?.(!!next.unresolved)
        noteCuaControl(threadId, heldFor(next))
        if (owner === 'stopped') noteCuaTurnEnded(threadId, 'stopped')
      }
    } catch (e) {
      // A transfer that a Stop just overtook failing is the Stop working.
      if (alive.current && (owner === 'stopped' || !stopping.current)) {
        setError(e instanceof Error ? e.message : String(e)); setFresh(false)
      }
    } finally {
      busy.current -= 1
      if (owner === 'stopped') stopping.current = false
      if (alive.current && !busy.current) setPending(null)
    }
  }

  // Nothing until the host has answered: claiming "connecting" for one request reads as a glitch.
  // A task the card already shows as ended offers no controls, whatever the last poll said.
  if (!state || ((!state.active || ended) && !state.unresolved)) return null
  if (!state.available) return <p className="px-3 py-2 text-xs text-ds-muted">{t('cuaControlUnavailable')}</p>
  const status = pending === 'user' || state?.transferring ? 'cuaControlTransferring'
    : pending === 'assistant' ? 'cuaControlResuming'
      : !fresh ? 'cuaControlDisconnected'
        : state?.unresolved ? 'cuaControlUnknown'
          : state?.awaiting_permission ? 'cuaControlPermission'
          : state?.owner === 'user' ? 'cuaControlHuman'
            : state?.waiting ? 'cuaControlWaiting'
              : state?.paused ? 'cuaControlPaused' : state?.active ? 'cuaControlAgent' : 'cuaPreviewEnded'
  const returning = state?.owner === 'user' || (!!state?.paused && !state?.unresolved) || (!state?.active && !!state?.unresolved)
  const inline = stopTarget !== undefined
  const stop = <button type="button" hidden={!state.active} disabled={pending === 'stopped'}
    aria-label={t('cuaControlStop')} title={t('cuaControlStop')}
    className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover disabled:opacity-40 focus-visible:outline focus-visible:outline-2"
    onClick={() => setConfirmStopTurn(state.turn_id)}><Square className="h-3 w-3 fill-current" strokeWidth={0} aria-hidden /></button>
  const needsAttention = returning || state.unresolved || state.waiting || state.awaiting_permission || state.transferring || error || !fresh
  return <>
    {confirmStopTurn && state.active && state.turn_id === confirmStopTurn && <ConfirmDialog
      title={t('cuaControlStopConfirmTitle')} body={t('cuaControlStopConfirmBody')}
      confirmLabel={t('cuaControlStopConfirm')} cancelLabel={t('cancel')}
      onCancel={() => setConfirmStopTurn(null)}
      onConfirm={() => { setConfirmStopTurn(null); void transfer('stopped') }} />}
    {inline && stopTarget && createPortal(stop, stopTarget)}
    {(!inline || needsAttention) && <div className="border-t border-ds-border px-3 py-2 text-xs" onPointerDown={event => event.stopPropagation()}>
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
      {!inline && <button type="button" hidden={!state.active} disabled={pending === 'stopped'} className="ml-auto rounded-full border border-ds-border bg-white dark:bg-ds-card px-3 py-1 text-ds-ink hover:bg-ds-hover disabled:opacity-40"
        onClick={() => setConfirmStopTurn(state.turn_id)}>{t('cuaControlStop')}</button>}
    </div> : null}
  </div>}
  </>
}
