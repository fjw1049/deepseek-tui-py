import { useCallback, useEffect, useRef, useState } from 'react'

type NavKeyEvent = {
  key: string
  preventDefault: () => void
}

/**
 * Arrow/Home/End highlight + Enter commit for Combobox-style lists.
 * Resets to 0 when the list length changes or the surface closes.
 */
export function useComboboxNav(itemCount: number, active: boolean): {
  highlighted: number
  setHighlighted: (index: number) => void
  onKeyDown: (event: NavKeyEvent, onEnter?: (index: number) => void) => boolean
} {
  const [highlighted, setHighlighted] = useState(0)
  const highlightedRef = useRef(0)
  highlightedRef.current = highlighted

  useEffect(() => {
    if (!active) return
    setHighlighted(0)
  }, [active, itemCount])

  const onKeyDown = useCallback(
    (event: NavKeyEvent, onEnter?: (index: number) => void): boolean => {
      if (!active || itemCount <= 0) return false
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setHighlighted((index) => (index + 1) % itemCount)
        return true
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setHighlighted((index) => (index - 1 + itemCount) % itemCount)
        return true
      }
      if (event.key === 'Home') {
        event.preventDefault()
        setHighlighted(0)
        return true
      }
      if (event.key === 'End') {
        event.preventDefault()
        setHighlighted(itemCount - 1)
        return true
      }
      if (event.key === 'Enter' && onEnter) {
        event.preventDefault()
        onEnter(highlightedRef.current)
        return true
      }
      return false
    },
    [active, itemCount]
  )

  return { highlighted, setHighlighted, onKeyDown }
}
