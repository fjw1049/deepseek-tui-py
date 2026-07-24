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
 *
 * Already-terminal cards loaded from history (restart / reopen thread) skip the
 * linger — only items that were observed active in this mount fade out.
 */
export function useDockSubagents(blocks: ChatBlock[]): DockSubagentView[] {
  const items = extractSubagentsFromBlocks(blocks)
  const terminalAtRef = useRef(new Map<string, number>())
  const seenActiveRef = useRef(new Set<string>())
  const [now, setNow] = useState(() => Date.now())

  for (const item of items) {
    if (isActiveSubagentStatus(item.status)) {
      seenActiveRef.current.add(item.id)
      terminalAtRef.current.delete(item.id)
    } else if (seenActiveRef.current.has(item.id) && !terminalAtRef.current.has(item.id)) {
      terminalAtRef.current.set(item.id, Date.now())
    }
  }
  const liveIds = new Set(items.map((item) => item.id))
  for (const id of [...terminalAtRef.current.keys()]) {
    if (!liveIds.has(id)) terminalAtRef.current.delete(id)
  }
  for (const id of [...seenActiveRef.current]) {
    if (!liveIds.has(id)) seenActiveRef.current.delete(id)
  }

  const needsTick = items.some(
    (item) => !isActiveSubagentStatus(item.status) && terminalAtRef.current.has(item.id)
  )
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
    const started = terminalAtRef.current.get(item.id)
    if (started == null) continue
    const age = now - started
    if (age >= HOLD_MS + FADE_MS) continue
    visible.push({ ...item, fading: age >= HOLD_MS })
  }
  return visible
}
