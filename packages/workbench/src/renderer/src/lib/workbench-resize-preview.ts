export type WorkbenchPanelWidths = { left: number; right: number; chatHidden: boolean }

/** Cache the hosts once; pointer frames only write styles, never measure or render content. */
export function createWorkbenchResizePreview(shell: HTMLElement, leftVisible: boolean, rightVisible: boolean) {
  const sidebar = shell.querySelector<HTMLElement>('.ds-workbench-sidebar-wrap')
  const slide = sidebar?.querySelector<HTMLElement>('.ds-workbench-sidebar-slide')
  const right = shell.querySelector<HTMLElement>('.ds-workbench-right-panel')
  const surface = right?.querySelector<HTMLElement>('.ds-right-panel-surface')
  const chat = shell.querySelector<HTMLElement>('.ds-chat-column')
  return ({ left, right: width, chatHidden }: WorkbenchPanelWidths): void => {
    if (leftVisible) {
      shell.style.setProperty('--ds-sidebar-width', `${left}px`)
      if (sidebar) sidebar.style.width = `${left}px`
      if (slide) slide.style.width = `${left}px`
    }
    if (!rightVisible) return
    if (right) {
      right.style.width = chatHidden ? '100%' : `${width}px`
      right.toggleAttribute('data-fill-width', chatHidden)
    }
    if (surface) {
      surface.style.width = `${width}px`
      surface.style.minWidth = chatHidden ? '100%' : ''
      surface.style.maxWidth = chatHidden ? '100%' : ''
    }
    if (chat) {
      chat.setAttribute('aria-hidden', String(chatHidden))
      chat.inert = chatHidden
      if (!chatHidden) chat.style.removeProperty('--ds-chat-rest-width')
    }
  }
}
