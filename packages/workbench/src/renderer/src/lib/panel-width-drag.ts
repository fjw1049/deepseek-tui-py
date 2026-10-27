/** Convert screen movement to layout pixels and discard travel beyond either edge. */
export function createPanelWidthDrag(
  pane: HTMLElement, clientX: number, fallbackWidth: number,
  min: number, max: number, direction: 1 | -1, parentFraction = 1
): (clientX: number) => number {
  const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
  const parentWidth = pane.parentElement?.clientWidth
  const limit = parentWidth ? Math.min(max, parentWidth * parentFraction) : max
  const clamp = (value: number): number => Math.min(limit, Math.max(min, value))
  let width = clamp(pane.getBoundingClientRect().width / scale || fallbackWidth)
  let previousX = clientX
  return (nextX) => {
    width = clamp(width + direction * (nextX - previousX) / scale)
    previousX = nextX
    return width
  }
}
