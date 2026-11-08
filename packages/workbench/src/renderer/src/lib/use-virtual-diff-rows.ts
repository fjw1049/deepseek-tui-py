import { useCallback, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'

/** Variable-height windowing: wrap/resize changes invalidate measured heights. */
export function useVirtualDiffRows(
  viewport: RefObject<HTMLDivElement | HTMLPreElement | null>,
  lengths: number[],
  wrap: boolean,
  split: boolean,
  identity: unknown
) {
  const [view, setView] = useState({ top: 0, width: 800, height: 600 })
  const [revision, setRevision] = useState(0)
  const measured = useRef(new Map<number, number>())
  const enabled = lengths.length > 200
  const columns = Math.max(1, Math.floor((view.width / (split ? 2 : 1) - 96) / 8.5))
  useLayoutEffect(() => {
    measured.current.clear()
    setRevision(value => value + 1)
  }, [identity, wrap, split, view.width])
  useLayoutEffect(() => {
    const node = viewport.current
    if (!node || !enabled) return
    let frame = 0
    const update = () => {
      frame = 0
      const next = { top: node.scrollTop, width: node.clientWidth || 800, height: node.clientHeight || 600 }
      setView(previous => previous.top === next.top && previous.width === next.width && previous.height === next.height ? previous : next)
    }
    const scroll = () => { if (!frame) frame = requestAnimationFrame(update) }
    const observer = new ResizeObserver(scroll)
    observer.observe(node)
    node.addEventListener('scroll', scroll, { passive: true })
    update()
    return () => { observer.disconnect(); node.removeEventListener('scroll', scroll); cancelAnimationFrame(frame) }
  }, [enabled, viewport])
  const offsets = useMemo(() => {
    void revision // Recompute offsets after ResizeObserver updates the measurement map.
    const values = [0]
    lengths.forEach((length, index) => values.push(values[index] + (measured.current.get(index) ??
      23 * (wrap ? Math.max(1, Math.ceil(length / columns)) : 1))))
    return values
  }, [lengths, wrap, columns, revision])
  const find = useCallback((top: number) => {
    let low = 0, high = lengths.length
    while (low < high) {
      const mid = (low + high) >>> 1
      if (offsets[mid + 1] <= top) low = mid + 1
      else high = mid
    }
    return low
  }, [lengths.length, offsets])
  const start = enabled ? Math.max(0, find(view.top) - 8) : 0
  const end = enabled ? Math.min(lengths.length, find(view.top + view.height) + 9) : lengths.length
  useLayoutEffect(() => {
    if (!enabled) return
    const node = viewport.current
    if (!node) return
    const observer = new ResizeObserver(() => {
      let changed = false
      let correction = 0
      const anchor = find(node.scrollTop)
      for (const row of node.querySelectorAll<HTMLElement>('[data-virtual-row]')) {
        const index = Number(row.dataset.virtualRow)
        const height = row.offsetHeight
        if (height > 0 && measured.current.get(index) !== height) {
          if (index < anchor) correction += height - (offsets[index + 1] - offsets[index])
          measured.current.set(index, height)
          changed = true
        }
      }
      if (changed) {
        if (correction) node.scrollTop += correction
        setView(previous => ({ ...previous, top: node.scrollTop }))
        setRevision(value => value + 1)
      }
    })
    for (const row of node.querySelectorAll('[data-virtual-row]')) observer.observe(row)
    return () => observer.disconnect()
  }, [enabled, start, end, identity, wrap, view.width, revision, viewport, find, offsets])
  return {
    enabled, start, end, offsets,
    before: offsets[start], after: offsets[lengths.length] - offsets[end],
    width: Math.max(0, ...lengths) * 8.5 * (split ? 2 : 1) + (split ? 160 : 96)
  }
}
