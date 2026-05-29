export type PetEventKind = 'user_message' | 'turn_complete' | 'turn_error' | 'wave' | 'jump'

type PetEventListener = (kind: PetEventKind) => void

const listeners = new Set<PetEventListener>()

export function subscribePetEvents(listener: PetEventListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function emitPetEvent(kind: PetEventKind): void {
  for (const listener of listeners) {
    listener(kind)
  }
}
