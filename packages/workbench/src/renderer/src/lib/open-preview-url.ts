export const OPEN_PREVIEW_URL_EVENT = 'deepseekgui:open-preview-url'

export type OpenPreviewUrlDetail = {
  url: string
}

export function openPreviewUrl(url: string): void {
  const trimmed = url.trim()
  if (!trimmed) return
  window.dispatchEvent(
    new CustomEvent<OpenPreviewUrlDetail>(OPEN_PREVIEW_URL_EVENT, {
      detail: { url: trimmed }
    })
  )
}
