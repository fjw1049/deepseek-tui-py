import { useChatStore } from '../store/chat-store'

/** Bridge so the settings sidebar "back" control can flush saves owned by SettingsView. */

type LeaveHandler = () => void

let leaveHandler: LeaveHandler | null = null

export function setSettingsLeaveHandler(handler: LeaveHandler | null): void {
  leaveHandler = handler
}

export function requestLeaveSettings(): void {
  if (leaveHandler) {
    leaveHandler()
    return
  }
  // Content not mounted yet — still exit the route.
  useChatStore.getState().setRoute('chat')
}
