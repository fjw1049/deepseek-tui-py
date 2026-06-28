import { useCallback } from 'react'
import { useDisclosureStore } from './disclosure-store'

/**
 * Persistent expand/collapse state for a keyed disclosure (e.g. a tool card).
 * Returns `[open, setOpen, hasStoredOpen]`. The third value is true when an
 * explicit value was stored, so callers can distinguish "user never touched
 * this" from "user collapsed it" when deciding auto-open behaviour.
 */
export function useDisclosure(
  key: string,
  defaultOpen: boolean
): [boolean, (open: boolean) => void, boolean] {
  const stored = useDisclosureStore((state) => state.disclosureById[key])
  const setDisclosure = useDisclosureStore((state) => state.setDisclosure)
  const open = stored ?? defaultOpen
  const setOpen = useCallback(
    (next: boolean) => setDisclosure(key, next),
    [setDisclosure, key]
  )
  return [open, setOpen, stored !== undefined]
}
