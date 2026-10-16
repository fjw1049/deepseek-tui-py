import { useCallback, useLayoutEffect, useRef } from 'react'

/**
 * Stable function identity that always runs the latest `fn`. Lets a memoised
 * child skip parent re-renders while the handler still sees current state.
 * Not for calls during render: the latest `fn` is installed in a layout effect.
 */
export function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn)
  useLayoutEffect(() => {
    ref.current = fn
  })
  return useCallback((...args: A) => ref.current(...args), [])
}
