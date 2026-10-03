import { create } from 'zustand'

type Failure = { id: number; message: string }
let nextId = 0
export const useFeedbackStore = create<{
  failures: Failure[]
  dismiss: (id: number) => void
}>((set) => ({
  failures: [],
  dismiss: (id) => set((state) => ({ failures: state.failures.filter((item) => item.id !== id) }))
}))

/** Imperative actions (e.g. clipboard writes) cannot rely on a local error banner. */
export function reportActionError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error)
  useFeedbackStore.setState((state) => state.failures.some((item) => item.message === message)
    ? state
    : { failures: [...state.failures, { id: ++nextId, message }] })
}
