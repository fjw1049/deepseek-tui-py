import { createContext, useContext } from 'react'
import type { ChatBlock } from '../../agent/types'

/** Display-only run views must never target the active main conversation. */
export const ConversationScope = createContext<{
  blocks: ChatBlock[]
  workspace: string
  active: boolean
} | null>(null)
export const useConversationScope = () => useContext(ConversationScope)
