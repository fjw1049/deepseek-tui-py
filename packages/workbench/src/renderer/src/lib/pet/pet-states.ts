export type PetStateId =
  | 'idle'
  | 'running-right'
  | 'running-left'
  | 'waving'
  | 'jumping'
  | 'failed'
  | 'waiting'
  | 'running'
  | 'review'

export type PetStateDef = {
  id: PetStateId
  row: number
  /** How long each frame holds; the last frame usually lingers so a move settles. */
  frameMs: readonly number[]
  /** One-shot moves stop on their last frame instead of wrapping around. */
  once?: boolean
  /** Hold the first frame for a random span between cycles, so idle has a rhythm. */
  restMs?: readonly [min: number, max: number]
}

function evenFrames(count: number, ms: number, lastMs: number): number[] {
  return Array.from({ length: count }, (_, index) => (index === count - 1 ? lastMs : ms))
}

export const PET_STATES: readonly PetStateDef[] = [
  { id: 'idle', row: 0, frameMs: [280, 110, 110, 140, 140, 320], restMs: [2400, 7000] },
  // Slower cycle: these rows only play while strolling or being dragged.
  { id: 'running-right', row: 1, frameMs: evenFrames(8, 215, 295) },
  { id: 'running-left', row: 2, frameMs: evenFrames(8, 215, 295) },
  { id: 'waving', row: 3, frameMs: evenFrames(4, 140, 280), once: true },
  { id: 'jumping', row: 4, frameMs: evenFrames(5, 140, 280), once: true },
  { id: 'failed', row: 5, frameMs: evenFrames(8, 140, 240), once: true },
  { id: 'waiting', row: 6, frameMs: evenFrames(6, 150, 260) },
  { id: 'running', row: 7, frameMs: evenFrames(6, 120, 220) },
  { id: 'review', row: 8, frameMs: evenFrames(6, 150, 280) }
] as const

export const SPRITE_FRAME_W = 192
export const SPRITE_FRAME_H = 208

const stateById = new Map(PET_STATES.map((state) => [state.id, state]))

export function getPetStateDef(stateId: PetStateId): PetStateDef {
  return stateById.get(stateId) ?? PET_STATES[0]
}

export function petCycleMs(stateId: PetStateId): number {
  return getPetStateDef(stateId).frameMs.reduce((sum, ms) => sum + ms, 0)
}
