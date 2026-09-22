export type TerminalSplitDirection = 'right' | 'down'
export type TerminalLayout =
  | { id: string; type: 'pane' }
  | { id: string; type: 'split'; direction: TerminalSplitDirection; ratio: number; first: TerminalLayout; second: TerminalLayout }

export function terminalPaneIds(node: TerminalLayout): string[] {
  return node.type === 'pane' ? [node.id] : [...terminalPaneIds(node.first), ...terminalPaneIds(node.second)]
}

export function replaceTerminalPane(node: TerminalLayout, id: string, replacement: TerminalLayout): TerminalLayout {
  if (node.type === 'pane') return node.id === id ? replacement : node
  return { ...node, first: replaceTerminalPane(node.first, id, replacement), second: replaceTerminalPane(node.second, id, replacement) }
}

export function removeTerminalPane(node: TerminalLayout, id: string): TerminalLayout | null {
  if (node.type === 'pane') return node.id === id ? null : node
  const first = removeTerminalPane(node.first, id)
  const second = removeTerminalPane(node.second, id)
  return first && second ? { ...node, first, second } : first ?? second
}

export function resizeTerminalSplit(node: TerminalLayout, id: string, ratio: number): TerminalLayout {
  if (node.type === 'pane') return node
  if (node.id === id) return { ...node, ratio: Math.max(0.1, Math.min(0.9, ratio)) }
  return { ...node, first: resizeTerminalSplit(node.first, id, ratio), second: resizeTerminalSplit(node.second, id, ratio) }
}

type Rect = { left: number; top: number; width: number; height: number }
export function terminalLayoutRects(node: TerminalLayout | undefined): {
  panes: Record<string, Rect>
  splits: Array<Rect & { id: string; direction: TerminalSplitDirection; ratio: number }>
} {
  const panes: Record<string, Rect> = {}
  const splits: Array<Rect & { id: string; direction: TerminalSplitDirection; ratio: number }> = []
  function visit(current: TerminalLayout, rect: Rect): void {
    if (current.type === 'pane') { panes[current.id] = rect; return }
    splits.push({ ...rect, id: current.id, direction: current.direction, ratio: current.ratio })
    const { left, top, width, height } = rect
    if (current.direction === 'right') {
      visit(current.first, { ...rect, width: width * current.ratio })
      visit(current.second, { ...rect, left: left + width * current.ratio, width: width * (1 - current.ratio) })
    } else {
      visit(current.first, { ...rect, height: height * current.ratio })
      visit(current.second, { ...rect, top: top + height * current.ratio, height: height * (1 - current.ratio) })
    }
  }
  if (node) visit(node, { left: 0, top: 0, width: 100, height: 100 })
  return { panes, splits }
}
