import { create } from 'zustand'
import type { SubagentMailboxPayload, ToolEventPayload } from '../agent/types'

/**
 * Per-thread memory behind the computer-use preview card (the window the agent is
 * operating, shown beside the conversation).
 *
 *   armed            a computer-use call started; the card waits for its first frame.
 *   live             the owning thread's card is on screen.
 *   hidden-for-task  the user closed it; it stays closed for the rest of this turn.
 *   ended            the turn ended; its last frame and outcome remain until dismissed.
 *
 * Sessions are keyed by thread, so background work never moves the user's view: a
 * thread's card shows only while that thread is the one being viewed.
 */
export type CuaPreviewOutcome = 'ended' | 'completed' | 'stopped' | 'failed'

export type CuaPreviewPhase = 'armed' | 'live' | 'hidden-for-task' | 'ended'

/** A screenshot a computer-use call recorded; served by `/v1/cua/frames`. */
export type CuaPreviewStill = { itemId: string; assetId: string }

export type CuaPreviewSession = {
  phase: CuaPreviewPhase
  turnId: string | null
  /** Native app the runtime last touched; null for browser surfaces or before any. */
  appId: string | null
  surface: 'app' | 'browser' | null
  /** The latest call's own step title. */
  label: string | null
  still: CuaPreviewStill | null
  /** Bumped by every finished call so the live stream re-checks the app's window. */
  revision: number
  outcome?: CuaPreviewOutcome
  capturedAt?: number
}

export type CuaPreviewPosition = { x: number; y: number }

type State = {
  sessions: Record<string, CuaPreviewSession | undefined>
  /** Detached card position per thread, in viewport px; absent means docked. */
  floating: Record<string, CuaPreviewPosition | undefined>
}

export const CUA_TOOL = 'cua_js'

export function phaseOnCallStart(
  phase: CuaPreviewPhase | undefined,
  newTurn: boolean
): CuaPreviewPhase {
  if (phase === 'live' || phase === 'armed') return phase
  // A dismissed card stays closed for its task and re-arms on the next one.
  if (phase === 'hidden-for-task' && !newTurn) return phase
  return 'armed'
}

export function phaseOnViewed(phase: CuaPreviewPhase | undefined): CuaPreviewPhase | undefined {
  return phase === 'armed' ? 'live' : phase
}

export function phaseOnHide(phase: CuaPreviewPhase | undefined): CuaPreviewPhase | undefined {
  return phase === 'armed' || phase === 'live' ? 'hidden-for-task' : phase
}

/** A dismissed card ends closed; undefined drops the session without a done state. */
export function phaseOnTurnEnd(phase: CuaPreviewPhase | undefined): CuaPreviewPhase | undefined {
  return phase === undefined || phase === 'hidden-for-task' ? undefined : 'ended'
}

function stringField(value: unknown, key: string): string | null {
  const field = value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined
  return typeof field === 'string' && field.trim() ? field.trim() : null
}

/** What a finished computer-use call tells the preview, read from its item metadata. */
export function cuaCallResult(ev: ToolEventPayload): {
  surface: 'app' | 'browser' | null
  appId: string | null
  still: CuaPreviewStill | null
  label: string | null
} | null {
  const meta = ev.meta
  if (ev.status === 'running' || !meta || meta.tool_name !== CUA_TOOL) return null
  const kind = stringField(meta.cua_surface, 'kind')
  const surface = kind === 'app' || kind === 'browser' ? kind : null
  const images = Array.isArray(meta.images) ? meta.images : []
  const shot = images
    .filter((image) => stringField((image as { source?: unknown })?.source, 'kind') === 'cua')
    .map((image) => stringField(image, 'asset_id'))
    .filter((id): id is string => id !== null)
    .at(-1)
  return {
    surface,
    appId: surface === 'app' ? stringField(meta.cua_surface, 'app_id') : null,
    still: shot ? { itemId: ev.itemId, assetId: shot } : null,
    label: stringField(meta.tool_input, 'title')
  }
}

export const useCuaPreviewStore = create<State>(() => ({ sessions: {}, floating: {} }))

function update(threadId: string, next: (session: CuaPreviewSession | undefined) => CuaPreviewSession | undefined): void {
  useCuaPreviewStore.setState((state) => {
    const current = state.sessions[threadId]
    const session = next(current)
    return session === current ? state : { sessions: { ...state.sessions, [threadId]: session } }
  })
}

function withPhase(session: CuaPreviewSession | undefined, phase: CuaPreviewPhase | undefined) {
  return session && phase !== undefined && phase !== session.phase ? { ...session, phase } : session
}

/** Live tool start: only `cua_js` during a live turn arms the card. */
export function noteCuaCallStarted(threadId: string, turnId: string | null, ev: ToolEventPayload): void {
  if (!turnId || (ev.turnId && ev.turnId !== turnId) || ev.status !== 'running' || ev.toolName !== CUA_TOOL) return
  const label = stringField(ev.meta?.tool_input, 'title')
  update(threadId, (session) => {
    const newTurn = session?.turnId !== turnId
    const phase = phaseOnCallStart(session?.phase, newTurn)
    // A new task waits for its own target instead of showing the last task's window.
    const base: CuaPreviewSession = session && !newTurn
      ? session
      : { phase, turnId, appId: null, surface: null, label: null, still: null,
          revision: (session?.revision ?? 0) + 1 }
    return { ...base, phase, turnId, label: label ?? base.label }
  })
}

export function noteCuaCallFinished(threadId: string, ev: ToolEventPayload): void {
  const result = cuaCallResult(ev)
  if (!result) return
  update(threadId, (session) => {
    if (!session || session.phase === 'ended' || (ev.turnId && ev.turnId !== session.turnId)) return session
    const touched = result.surface !== null
    return {
      ...session,
      surface: touched ? result.surface : session.surface,
      appId: touched ? result.appId : session.appId,
      still: result.still ?? (touched && (result.surface !== session.surface || result.appId !== session.appId) ? null : session.still),
      capturedAt: result.still ? Date.now() : session.capturedAt,
      label: result.label ?? session.label,
      revision: session.revision + 1
    }
  })
}

/** The thread's turn finished or was stopped: end its card (idempotent). */
export function noteCuaTurnEnded(threadId: string, outcome: CuaPreviewOutcome = 'ended'): void {
  update(threadId, (session) => {
    const phase = phaseOnTurnEnd(session?.phase)
    if (!session || phase === undefined) return undefined
    return { ...session, phase, outcome: session.outcome && session.outcome !== 'ended' ? session.outcome : outcome }
  })
}

type MailboxMessage = SubagentMailboxPayload['message']

/**
 * A sub-agent's computer-use step, seen through its mailbox. It drives the parent
 * thread's card like the parent's own calls; its screenshots stay with the child.
 */
export function cuaEventFromMailbox(message: MailboxMessage): ToolEventPayload | null {
  if (message.tool_name !== CUA_TOOL) return null
  const itemId = message.tool_call_id ?? `${message.agent_id}:${message.step ?? ''}`
  if (message.kind === 'tool_call_started') {
    return { itemId, summary: CUA_TOOL, status: 'running', toolName: CUA_TOOL }
  }
  if (message.kind !== 'tool_call_completed') return null
  return {
    itemId,
    summary: CUA_TOOL,
    status: message.ok === false ? 'error' : 'success',
    meta: { tool_name: CUA_TOOL, cua_surface: message.cua_surface ?? undefined }
  }
}

export function markCuaPreviewLive(threadId: string): void {
  update(threadId, (session) => withPhase(session, phaseOnViewed(session?.phase)))
}

export function hideCuaPreviewForTask(threadId: string): void {
  update(threadId, (session) => withPhase(session, phaseOnHide(session?.phase)))
}

/** The ended card has been shown as done; drop it until the next computer-use call. */
export function dismissEndedCuaPreview(threadId: string): void {
  update(threadId, (session) => (session?.phase === 'ended' ? undefined : session))
}

export function setCuaPreviewFloating(threadId: string, position: CuaPreviewPosition | null): void {
  useCuaPreviewStore.setState((state) => {
    const floating = { ...state.floating }
    if (position) floating[threadId] = position
    else delete floating[threadId]
    return { floating }
  })
}

/** Visibility never changes control ownership. */
export function showCuaPreview(threadId: string): void {
  update(threadId, (session) => session?.phase === 'hidden-for-task'
    ? { ...session, phase: 'live' } : session)
}

/** Reconnect to a live host session without replaying historical tool events. */
export function restoreCuaPreview(threadId: string, state: {
  used: boolean; active: boolean; turn_id: string | null
  unresolved?: unknown; surface?: { kind: string; app_id?: string } | null
}): void {
  if (!state.used || (!state.active && !state.unresolved) || !state.turn_id) return
  update(threadId, session => session?.turnId === state.turn_id ? session : {
    phase: state.active ? 'armed' : 'ended', turnId: state.turn_id,
    surface: state.surface?.kind === 'app' ? 'app' : state.surface?.kind === 'browser' ? 'browser' : null,
    appId: state.surface?.app_id ?? null, label: null, still: null, revision: 0
  })
}
