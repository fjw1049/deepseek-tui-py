import { useEffect, useRef, useState } from 'react'
import {
  extractSubagentsFromBlocks,
  isActiveSubagentStatus,
  type DockSubagentItem
} from '../lib/extract-subagents-from-blocks'
import type { ChatBlock } from '../agent/types'

/** Keep finished subagents in the dock briefly, then fade them out. */
const HOLD_MS = 8_000
const FADE_MS = 450
const TICK_MS = 200

export type DockSubagentView = DockSubagentItem & { fading: boolean }

/**
 * Live subagents from the timeline, plus a short post-terminal linger so the
 * operator can see completion/failure before the row disappears.
 */
export function useDockSubagents(blocks: ChatBlock[]): DockSubagentView[] {
  const items = extractSubagentsFromBlocks(blocks)
  const terminalAtRef = useRef(new Map<string, number>())
  const [now, setNow] = useState(() => Date.now())

  for (const item of items) {
    if (isActiveSubagentStatus(item.status)) {
      terminalAtRef.current.delete(item.id)
    } else if (!terminalAtRef.current.has(item.id)) {
      terminalAtRef.current.set(item.id, Date.now())
    }
  }
  const liveIds = new Set(items.map((item) => item.id))
  for (const id of [...terminalAtRef.current.keys()]) {
    if (!liveIds.has(id)) terminalAtRef.current.delete(id)
  }

  const needsTick = items.some((item) => !isActiveSubagentStatus(item.status))
  useEffect(() => {
    if (!needsTick) return
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS)
    return () => window.clearInterval(timer)
  }, [needsTick])

  const visible: DockSubagentView[] = []
  for (const item of items) {
    if (isActiveSubagentStatus(item.status)) {
      visible.push({ ...item, fading: false })
      continue
    }
    const started = terminalAtRef.current.get(item.id) ?? now
    const age = now - started
    if (age >= HOLD_MS + FADE_MS) continue
    visible.push({ ...item, fading: age >= HOLD_MS })
  }
  return visible
}
