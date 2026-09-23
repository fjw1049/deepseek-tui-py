import type { ChatArrangement } from '../store/chat-layout-store'

export type ChatSplitPresentation = ChatArrangement

export function resolveChatSplitPresentation(count: number, requested: ChatArrangement, width: number, height: number): ChatSplitPresentation {
  if (count <= 1) return requested === 'tabs' ? 'grid' : requested
  if (requested === 'tabs') return 'tabs'
  if (width <= 0 || height <= 0) return requested
  const fits = (arrangement: ChatArrangement): boolean => {
    const columns = arrangement === 'vertical' ? 1 : arrangement === 'horizontal' ? count : count > 4 ? 3 : 2
    const rows = arrangement === 'vertical' ? count : arrangement === 'horizontal' ? 1 : count > 2 ? 2 : 1
    return width / columns >= 360 && height / rows >= 260
  }
  return fits(requested) ? requested : fits('grid') ? 'grid' : 'tabs'
}
