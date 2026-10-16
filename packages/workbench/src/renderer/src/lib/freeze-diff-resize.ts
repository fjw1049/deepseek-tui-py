/** Freeze only wrapped diff tables while the surrounding panel follows the pointer. */
export function freezeDiffResize(root: HTMLElement): () => void {
  const restore: Array<() => void> = []
  for (const table of root.querySelectorAll<HTMLTableElement>('.ds-diff-view[data-wrap] .ds-diff-table')) {
    const width = table.offsetWidth
    const viewport = table.parentElement
    if (!width || !viewport || !viewport.clientHeight) continue
    const view = table.closest<HTMLElement>('.ds-diff-view')!
    const path = view.dataset.diffPath
    const oldWidth = table.style.width
    const oldMin = table.style.minWidth
    const oldMax = table.style.maxWidth
    const oldAnchor = viewport.style.overflowAnchor
    const oldOverflowX = viewport.style.overflowX
    const scrollTop = viewport.scrollTop
    const scrollLeft = viewport.scrollLeft
    const bounds = viewport.getBoundingClientRect()
    let anchor: HTMLTableRowElement | undefined
    let fraction = 0
    if (scrollTop > 0) {
      // Find the first visible row without walking every line in a large file.
      let low = 0
      let high = table.rows.length
      while (low < high) {
        const mid = (low + high) >>> 1
        if (table.rows[mid].getBoundingClientRect().bottom <= bounds.top) low = mid + 1
        else high = mid
      }
      anchor = table.rows[low]
      if (anchor) {
        const row = anchor.getBoundingClientRect()
        fraction = row.height ? Math.max(0, Math.min(1, (bounds.top - row.top) / row.height)) : 0
      }
    }
    viewport.style.overflowAnchor = 'none'
    viewport.style.overflowX = 'hidden'
    table.style.width = `${width}px`
    table.style.minWidth = `${width}px`
    table.style.maxWidth = `${width}px`
    restore.push(() => {
      table.style.width = oldWidth
      table.style.minWidth = oldMin
      table.style.maxWidth = oldMax
      viewport.style.overflowX = oldOverflowX
      if (table.isConnected && view.dataset.diffPath === path) {
        if (anchor?.isConnected && table.contains(anchor)) {
          const nextBounds = viewport.getBoundingClientRect()
          const row = anchor.getBoundingClientRect()
          const scale = nextBounds.height / viewport.offsetHeight || 1
          viewport.scrollTop += (row.top - nextBounds.top + fraction * row.height) / scale
        } else if (scrollTop === 0) viewport.scrollTop = 0
        viewport.scrollLeft = scrollLeft
      }
      viewport.style.overflowAnchor = oldAnchor
    })
  }
  let restored = false
  return () => {
    if (restored) return
    restored = true
    for (const apply of restore) apply()
  }
}
