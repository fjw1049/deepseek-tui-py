import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Exit-animation helper for conditionally rendered popovers. Pair it with the
 * enter animation (`ds-pop` / per-menu CSS): `requestClose()` keeps the node
 * mounted for `ms` (call `setOpen(false)` right after) so the `ds-pop-out`
 * fade can play, then `closing` flips false and the node unmounts.
 */
export function usePopExit(
  open: boolean,
  ms = 110
): { closing: boolean; requestClose: () => void } {
  const [closing, setClosing] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!open) return
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    setClosing(false)
  }, [open])

  useEffect(
    () => () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current)
    },
    []
  )

  const requestClose = useCallback((): void => {
    if (timerRef.current != null) return
    setClosing(true)
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setClosing(false)
    }, ms)
  }, [ms])

  return { closing, requestClose }
}
