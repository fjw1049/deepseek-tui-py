import { subscribeAllPetEvents } from './pet-events'

const waitingByThread = new Map<string, Set<string>>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

export function clearPetAttention(threadId: string): void {
  if (waitingByThread.delete(threadId)) notify()
}

function setItem(threadId: string, itemId: string, waiting: boolean): void {
  const items = waitingByThread.get(threadId) ?? new Set<string>()
  if (waiting) items.add(itemId)
  else items.delete(itemId)
  if (items.size) waitingByThread.set(threadId, items)
  else waitingByThread.delete(threadId)
  notify()
}

// Registered once for the app: a pane's pet only hears its own thread, while
// this keeps listening to every session whose event stream is still attached.
subscribeAllPetEvents((threadId, event) => {
  if (!threadId) return
  if (event.type === 'approval_waiting' || event.type === 'elevation_waiting' ||
    event.type === 'user_input_waiting') {
    setItem(threadId, event.itemId, true)
  } else if (event.type === 'approval_resolved' || event.type === 'elevation_resolved' ||
    event.type === 'user_input_resolved') {
    setItem(threadId, event.itemId, false)
  } else if (event.type === 'turn_complete' || event.type === 'user_message') {
    clearPetAttention(threadId)
  }
})

export function subscribePetAttention(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function firstOtherWaitingThread(threadId: string | null): string | null {
  for (const id of waitingByThread.keys()) {
    if (id !== threadId) return id
  }
  return null
}
