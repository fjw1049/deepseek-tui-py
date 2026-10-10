import { create } from 'zustand'
import type { Assistance } from '../components/BrowserAssistanceCard'

/** Live requests shared by the notification monitor and the pending-decision panel. */
export const useBrowserAssistanceStore = create<{
  items: Assistance[]
  connectionError: string
  revision: number
}>(() => ({ items: [], connectionError: '', revision: 0 }))
