import { useEffect, useState } from 'react'
import { PREFERRED_EDITOR_CHANGED_EVENT } from '../lib/editor-preferences'
import { resolvePreferredEditorLabel } from '../lib/open-workspace-path'

/** Keeps the "Open with XX" label in sync with the user's preferred editor. */
export function usePreferredEditorLabel(fallback: string): string {
  const [label, setLabel] = useState(fallback)

  useEffect(() => {
    let cancelled = false

    const refresh = (): void => {
      void resolvePreferredEditorLabel(fallback).then((next) => {
        if (!cancelled) setLabel(next)
      })
    }

    refresh()
    window.addEventListener(PREFERRED_EDITOR_CHANGED_EVENT, refresh)
    window.addEventListener('focus', refresh)
    return () => {
      cancelled = true
      window.removeEventListener(PREFERRED_EDITOR_CHANGED_EVENT, refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [fallback])

  return label
}
