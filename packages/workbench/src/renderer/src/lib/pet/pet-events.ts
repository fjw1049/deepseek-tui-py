import type { ToolItemKind } from '../../agent/types'
import type { PetTurnDigest } from './pet-turn-digest'

export type PetActivityEvent =
  | { type: 'user_message'; text?: string }
  | { type: 'agent_reasoning' }
  | { type: 'tool_started'; itemId: string; summary: string; toolKind?: ToolItemKind }
  | {
      type: 'tool_completed'
      itemId: string
      status: 'success' | 'error'
      summary: string
      toolKind?: ToolItemKind
    }
  | { type: 'approval_waiting'; itemId: string; toolName?: string }
  | { type: 'approval_resolved'; itemId: string; status: 'allowed' | 'denied' | 'error' }
  | { type: 'elevation_waiting'; itemId: string; toolName?: string }
  | { type: 'elevation_resolved'; itemId: string; status: 'allowed' | 'denied' | 'error' }
  | { type: 'user_input_waiting'; itemId: string }
  | { type: 'user_input_resolved'; itemId: string; status: 'submitted' | 'cancelled' | 'error' }
  | { type: 'subagent_started'; itemId: string; agentType: string }
  | { type: 'subagent_completed'; itemId: string; status: 'completed' | 'failed' | 'cancelled' }
  | { type: 'turn_complete'; digest: PetTurnDigest }
  | { type: 'turn_error' }

/** Window event: the waiting pet was clicked, so show the request it is waiting on. */
export const PET_REVEAL_DECISION_EVENT = 'deepseekgui:pet-reveal-decision'

type PetEventListener = (threadId: string | null, event: PetActivityEvent) => void

const listeners = new Set<PetEventListener>()

export function subscribeAllPetEvents(listener: PetEventListener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function subscribePetEvents(
  threadId: string | null,
  listener: (event: PetActivityEvent) => void
): () => void {
  return subscribeAllPetEvents((sourceThreadId, event) => {
    if (sourceThreadId === threadId) listener(event)
  })
}

export function emitPetEvent(threadId: string | null, event: PetActivityEvent): void {
  for (const listener of listeners) {
    listener(threadId, event)
  }
}
