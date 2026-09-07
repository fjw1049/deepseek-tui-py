import { create } from 'zustand'
import { useChatStore } from './chat-store'

export type RunTarget = { threadId: string; kind: 'task' | 'subagent'; id: string }

type RunPanelState = {
  target: RunTarget | null
  request: number
  open: (target: RunTarget) => void
}

// Selection survives closing the view; execution and stream ownership stay elsewhere.
export const useRunPanelStore = create<RunPanelState>((set) => ({
  target: null,
  request: 0,
  open: (target) => set((state) => ({ target, request: state.request + 1 }))
}))

export function openRunPanel(target: Omit<RunTarget, 'threadId'>): void {
  const threadId = useChatStore.getState().activeThreadId
  if (threadId) useRunPanelStore.getState().open({ ...target, threadId })
}
