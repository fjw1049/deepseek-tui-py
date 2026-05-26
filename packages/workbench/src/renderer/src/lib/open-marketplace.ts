export function openExternalUrl(url: string): void {
  if (typeof window.dsGui?.openExternal !== 'function') return
  void window.dsGui.openExternal(url)
}
