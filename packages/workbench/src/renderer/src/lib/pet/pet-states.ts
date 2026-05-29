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
  frames: number
  durationMs: number
}

export const PET_STATES: readonly PetStateDef[] = [
  { id: 'idle', row: 0, frames: 6, durationMs: 1100 },
  { id: 'running-right', row: 1, frames: 8, durationMs: 1060 },
  { id: 'running-left', row: 2, frames: 8, durationMs: 1060 },
  { id: 'waving', row: 3, frames: 4, durationMs: 700 },
  { id: 'jumping', row: 4, frames: 5, durationMs: 840 },
  { id: 'failed', row: 5, frames: 8, durationMs: 1220 },
  { id: 'waiting', row: 6, frames: 6, durationMs: 1010 },
  { id: 'running', row: 7, frames: 6, durationMs: 820 },
  { id: 'review', row: 8, frames: 6, durationMs: 1030 }
] as const

export const SPRITE_FRAME_W = 192
export const SPRITE_FRAME_H = 208
export const SPRITE_SHEET_W = 1536
export const SPRITE_SHEET_H = 1872

const stateById = new Map(PET_STATES.map((state) => [state.id, state]))

export function getPetStateDef(stateId: PetStateId): PetStateDef {
  return stateById.get(stateId) ?? PET_STATES[0]
}
