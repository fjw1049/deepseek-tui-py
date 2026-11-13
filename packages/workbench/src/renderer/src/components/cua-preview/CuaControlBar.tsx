import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ConfirmDialog } from '../workspace-editor/ConfirmDialog'
import { Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { noteCuaControl, noteCuaTurnEnded, restoreCuaPreview, useCuaPreviewStore } from '../../store/cua-preview-store'

const ACTIVE_POLL_MS = 1_000
/** Nothing changes between tasks, and the next task's calls ask for a refresh themselves. */
const IDLE_POLL_MS = 3_000

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

/**
 * Keeps the card in step with the host and offers Stop. It shows no status of its own:
 * whatever needs the person (app permission, a manual step) is asked in the conversation.
 */
export function CuaControlBar({ threadId, stopTarget, onConnectionChange }: {
  threadId: string; stopTarget?: HTMLElement | null
  onConnectionChange?: (turnId: string | null) => void
}): React.JSX.Element | null {
  const { t } = useTranslation('common')
  const [state, setState] = useState<CuaControlState | null>(null)
  const [confirmStopTurn, setConfirmStopTurn] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const alive = useRef(true)
  const busy = useRef(0)
  const pollNow = useRef<() => void>(() => undefined)
  const requestVersion = useRef(0)
  const path = `/v1/threads/${encodeURIComponent(threadId)}/cua`
  useEffect(() => {
    alive.current = true
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    let inFlight = false
    let again = false
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
          if (!response.ok) throw new Error(response.body)
          const value = JSON.parse(response.body) as CuaControlState
          if (!disposed && version === requestVersion.current) {
            setState(controllable(value))
            onConnectionChange?.(value.active && value.available && value.used !== false && !value.waiting && !value.awaiting_permission ? value.turn_id : null)
            noteCuaControl(threadId, heldFor(value))
            restoreCuaPreview(threadId, { ...value, used: value.used === true })
            const over = !value.active
            if (over) delay = IDLE_POLL_MS
            idlePolls = over ? idlePolls + 1 : 0
            // A completion event lost with the stream must not leave the card live. Twice,
            // because a response can predate the turn that just armed the card.
            if (idlePolls === 2) noteCuaTurnEnded(threadId)
          }
        } catch {
          if (!disposed) onConnectionChange?.(null)
          // The next poll tries again; Stop stays usable meanwhile.
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
  }, [path, threadId, onConnectionChange])

  // Calls and handoffs change control at once; do not make them wait for the next poll.
  const revision = useCuaPreviewStore(store => store.sessions[threadId]?.revision)
  const ended = useCuaPreviewStore(store => store.sessions[threadId]?.phase === 'ended')
  const seenRevision = useRef(revision)
  useEffect(() => {
    if (seenRevision.current === revision) return
    seenRevision.current = revision
    pollNow.current()
  }, [revision])

  const stop = async (): Promise<void> => {
    if (!state?.turn_id || stopping) return
    busy.current += 1; ++requestVersion.current; setStopping(true)
    try {
      const response = await window.dsGui.runtimeRequest(`${path}/control`, 'POST', JSON.stringify({
        owner: 'stopped', revision: state.revision, turn_id: state.turn_id
      }))
      if (!response.ok) return
      const next = JSON.parse(response.body) as CuaControlState
      if (alive.current) {
        setState(controllable(next))
        noteCuaControl(threadId, heldFor(next))
        noteCuaTurnEnded(threadId, 'stopped')
      }
    } catch {
      // Stop stays enabled, so the person can simply press it again.
    } finally {
      busy.current -= 1
      if (alive.current) setStopping(false)
    }
  }

  // A task the card already shows as ended offers no controls, whatever the last poll said.
  if (!state || !state.active || ended || !state.available) return null
  const button = <button type="button" disabled={stopping}
    aria-label={t('cuaControlStop')} title={t('cuaControlStop')}
    className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover disabled:opacity-40 focus-visible:outline focus-visible:outline-2"
    onClick={() => setConfirmStopTurn(state.turn_id)}><Square className="h-3 w-3 fill-current" strokeWidth={0} aria-hidden /></button>
  return <>
    {confirmStopTurn && state.turn_id === confirmStopTurn && <ConfirmDialog
      title={t('cuaControlStopConfirmTitle')} body={t('cuaControlStopConfirmBody')}
      confirmLabel={t('cuaControlStopConfirm')} cancelLabel={t('cancel')}
      onCancel={() => setConfirmStopTurn(null)}
      onConfirm={() => { setConfirmStopTurn(null); void stop() }} />}
    {stopTarget === undefined ? button : stopTarget ? createPortal(button, stopTarget) : null}
  </>
}
