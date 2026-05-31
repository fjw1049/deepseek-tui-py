import type { ToolItemKind } from '../../agent/types'

export type PetActivityEvent =
  | { type: 'user_message' }
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
  | { type: 'turn_complete' }
  | { type: 'turn_error' }
  | { type: 'manual_wave' }
  | { type: 'manual_jump' }

type LegacyPetEventKind = 'user_message' | 'turn_complete' | 'turn_error' | 'wave' | 'jump'

type PetEventListener = (event: PetActivityEvent) => void

const listeners = new Set<PetEventListener>()

function normalizePetEvent(event: PetActivityEvent | LegacyPetEventKind): PetActivityEvent {
  if (typeof event !== 'string') return event
  if (event === 'wave') return { type: 'manual_wave' }
  if (event === 'jump') return { type: 'manual_jump' }
  return { type: event }
}

export function subscribePetEvents(listener: PetEventListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function emitPetEvent(event: PetActivityEvent | LegacyPetEventKind): void {
  const normalized = normalizePetEvent(event)
  for (const listener of listeners) {
    listener(normalized)
  }
}
