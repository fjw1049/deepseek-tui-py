import { create } from 'zustand'

/**
 * Lightweight UI disclosure store — persists tool-card open/closed state
 * across remounts by key. Kept separate from `chat-store` so the heavy chat
 * state slice is untouched; this only holds expand/collapse flags.
 */
interface DisclosureState {
  disclosureById: Record<string, boolean>
  setDisclosure: (key: string, open: boolean) => void
  clearDisclosure: (key: string) => void
}

/**
 * Cap stored entries. Each tool call gets a unique `tool:${id}` key, so a long
 * session would otherwise grow this map without bound. We evict the oldest
 * (insertion-order) keys past the cap — they belong to turns far up the
 * scrollback that the user is unlikely to re-toggle.
 */
const MAX_DISCLOSURE_ENTRIES = 400

export const useDisclosureStore = create<DisclosureState>((set) => ({
  disclosureById: {},
  setDisclosure: (key, open) =>
    set((state) => {
      const next = { ...state.disclosureById, [key]: open }
      const keys = Object.keys(next)
      const overflow = keys.length - MAX_DISCLOSURE_ENTRIES
      if (overflow > 0) {
        for (let i = 0; i < overflow; i += 1) {
          if (keys[i] !== key) delete next[keys[i]!]
        }
      }
      return { disclosureById: next }
    }),
  clearDisclosure: (key) =>
    set((state) => {
      if (!(key in state.disclosureById)) return state
      const next = { ...state.disclosureById }
      delete next[key]
      return { disclosureById: next }
    })
}))
