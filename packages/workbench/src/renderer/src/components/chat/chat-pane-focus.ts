import { createContext, useContext } from 'react'

export const ChatPaneFocusContext = createContext(true)
export const useChatPaneFocused = (): boolean => useContext(ChatPaneFocusContext)
