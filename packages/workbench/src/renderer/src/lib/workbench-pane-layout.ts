export const RIGHT_PANEL_MIN = 260
export const CHAT_READING_MIN_WIDTH = 400
const CHAT_HIDE_THRESHOLD = 48

export function resolveRightPanelLayout(
  mainWidth: number,
  requestedRight: number
): { rightWidth: number; chatHidden: boolean } {
  const maxRight = Math.max(RIGHT_PANEL_MIN, mainWidth)
  const clamped = Math.min(maxRight, Math.max(RIGHT_PANEL_MIN, requestedRight))
  const remainingChat = mainWidth - clamped
  if (remainingChat <= CHAT_HIDE_THRESHOLD || mainWidth < RIGHT_PANEL_MIN + CHAT_READING_MIN_WIDTH) {
    return { rightWidth: mainWidth, chatHidden: true }
  }
  return { rightWidth: Math.min(clamped, mainWidth - CHAT_READING_MIN_WIDTH), chatHidden: false }
}
