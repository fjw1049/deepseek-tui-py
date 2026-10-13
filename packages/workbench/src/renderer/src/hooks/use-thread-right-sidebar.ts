import { useState } from 'react'
import { readStoredRightSidebarPanels, type RightSidebarPanels } from '../lib/right-sidebar-state'

type SidebarState = { open: boolean; collapsed: boolean; panels: RightSidebarPanels }

export function useThreadRightSidebar(threadId: string | null) {
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [panels, setPanels] = useState(readStoredRightSidebarPanels)
  const [sessions, setSessions] = useState(() => ({
    threadId, saved: new Map<string | null, SidebarState>()
  }))
  // Restore before children render, so the incoming thread never sees the old dock.
  if (sessions.threadId !== threadId) {
    const saved = new Map(sessions.saved)
    saved.set(sessions.threadId, { open, collapsed, panels })
    const next = saved.get(threadId)
    setSessions({ threadId, saved })
    setOpen(next?.open ?? false)
    setCollapsed(next?.collapsed ?? false)
    setPanels(next?.panels ?? { tabs: [], activeTab: null })
  }
  return { open, setOpen, collapsed, setCollapsed, panels, setPanels }
}
